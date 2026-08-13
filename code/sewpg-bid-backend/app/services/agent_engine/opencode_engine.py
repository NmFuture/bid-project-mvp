from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Any, Callable

import httpx

from app.core.config import settings
from app.services.agent_engine import errors as engine_errors
from app.services.agent_engine import json_utils
from app.services.agent_engine import orchestrator as agent_orchestrator
from app.services.agent_engine import trace as trace_utils
from app.services.agent_engine.base import (
    EarlyCompletionPlan,
    EngineRunResult,
    ToolCompletedEvent,
    iter_completed_bash_tool_events,
)
from app.services.agent_engine.concurrency import AGENT_CONCURRENCY_BUDGET
from app.services.bid_parse_cancel import ParseCancelledError
from app.services.system_settings import opencode_llm_config_active, system_settings_service


logger = logging.getLogger(__name__)

OPENCODE_PROGRESS_HEARTBEAT_SECONDS = 10.0
OPENCODE_EARLY_COMPLETION_STOP_TIMEOUT_SECONDS = 10.0

# B4（engine-06）：默认请求槽 = 全局并发预算本身（不另设 cap）；S1 分片槽与
# 目录章节槽从同一预算派生（见 parsing.py / outline_generation.py），总并发恒 ≤ 预算。
# 历史导出入口保留 `_OPENCODE_REQUEST_SLOTS` 名字（tests 与旧调用方从这里取）。
_OPENCODE_REQUEST_SLOTS = AGENT_CONCURRENCY_BUDGET.derive()
_SESSION_CREATE_RETRY_DELAYS_SEC = (0.5, 1.0, 2.0, 4.0, 8.0, 8.0)
# 与 errors.RETRYABLE_HTTP_STATUS_CODES 同源（B2 起唯一事实在 errors.py）。
_SESSION_CREATE_RETRYABLE_STATUS_CODES = engine_errors.RETRYABLE_HTTP_STATUS_CODES

# 历史导出入口（tests 与旧调用方从这里取）；常量的owner是编排层。
OUTLINE_DECISION_SESSION_MAX_ATTEMPTS = agent_orchestrator.OUTLINE_DECISION_SESSION_MAX_ATTEMPTS


class OpencodeEngine:
    """opencode（LLM Agent 运行时）HTTP 引擎：建会话、发 prompt、轮询会话进度。

    B1（engine-03）起全量 async：`httpx.AsyncClient` + 每会话一个 asyncio task
    轮询（原 daemon 线程已消除，轮询异常经 task 显式传回调用方）；心跳、
    idle 超时、进度增量与 on_tool_completed 提前收割语义不变。
    AsyncClient 沿用基线「按请求创建」的生命周期（同步版即每请求新建 Client），
    引擎实例可能被多个事件循环（asyncio.run 桥接的工作线程 / FastAPI 循环）
    复用，跨循环共享连接池不安全，故不在实例上持有长连接。

    B2（engine-04）落地可恢复错误治理（错误分类见 `agent_engine/errors.py`）：
    - `send_prompt` 只对「确认未送达」（连接未建立）按预算重发；送达状态不确定
      （读超时/5xx/中途断连）抛 `PromptDeliveryUncertainError`，不自动重发。
    - 轮询 GET 断线按退避重连（`_poll_session_messages`），断线时间不计入
      idle 监管（服务重启 ≠ 模型 stall）；预算耗尽抛 `PollReconnectExhaustedError`。
    重试次数/退避为配置项（`OPENCODE_SEND_PROMPT_MAX_RETRIES` 等，默认值本地安全）。

    B3（engine-05）落地会话生命周期回收：`delete_session`（DELETE /session/{id}，
    404 幂等、其余失败显式抛错）；编排层在会话终态经 `delete_session_quietly`
    回收（失败只告警不阻断）。唯一刻意保留的是 technical_chat_service 的
    多轮共创对话会话（`send_text_prompt(keep_session=True)`）。

    B4（engine-06）落地并发治理统一：默认请求槽不再是独立信号量池，而是
    全局并发预算 `AGENT_CONCURRENCY_BUDGET` 派生的 `BudgetPool`
    （`agent_engine/concurrency.py`）；S1 分片与目录章节池从同一预算派生，
    进程型引擎（codex/pi）进程池也并入该预算，总并发恒 ≤ `AGENT_CONCURRENCY_BUDGET`。

    A1（engine-02）后本类只剩引擎/传输层职责（改造方案 §1 A 层）：
    会话生命周期、轮询监管（idle 超时/心跳/取消）、「bash 工具完成」事件检测与
    提前收割框架、输出留痕。全部业务编排（`run_bid_*` / `_extract_*_json` /
    finalize 判定 / stall 报错）已上移到 `agent_engine/orchestrator.py`，
    本类以同名委托保留对外方法名与签名（B1 起为 async）。

    提前完成的业务差异通过 `EarlyCompletionPlan` 注入
    `_send_prompt_with_session_polling`：本文件不出现任何业务命令字符串字面量。
    """

    engine_name = "opencode"  # AgentEngine 协议属性（§3）

    _parse_json_payload = staticmethod(json_utils._parse_json_payload)
    _balanced_json_object_candidates = staticmethod(json_utils._balanced_json_object_candidates)
    _repair_json_payload = json_utils._repair_json_payload
    _build_output_trace = trace_utils._build_output_trace
    _coerce_timestamp = staticmethod(trace_utils._coerce_timestamp)
    _normalize_output_parts = staticmethod(trace_utils._normalize_output_parts)
    _format_response_error = staticmethod(engine_errors._format_response_error)
    is_model_not_found_error = staticmethod(engine_errors.is_model_not_found_error)
    _short_http_error = staticmethod(engine_errors._short_http_error)

    def __init__(
        self,
        *,
        base_url: str | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
        timeout_ms: int | float | None = None,
        model_config: dict[str, Any] | None = None,
        request_slots: Any | None = None,
    ) -> None:
        config = (
            model_config
            if model_config is not None
            else system_settings_service.get_opencode_model_config_sync()
        )
        # 自定义 LLM 未生效（禁用/未配置完整）时忽略 DB 的 provider/model/opencodeBaseUrl，
        # 回退到环境变量配置（与 opencode/docker-entrypoint.sh 的环境回退同源）
        db_active = opencode_llm_config_active(config)
        self.base_url = str(base_url or (config.get("opencodeBaseUrl") if db_active else "") or settings.opencode_base_url).rstrip("/")
        self.provider_id = str(provider_id or (config.get("providerId") if db_active else "") or settings.opencode_provider_id)
        self.model_id = str(model_id or ((config.get("modelId") or config.get("model")) if db_active else "") or settings.opencode_model_id)
        raw_timeout_ms = timeout_ms if timeout_ms is not None else config.get("timeoutMs")
        timeout_sec = max(1.0, float(raw_timeout_ms or settings.opencode_timeout_sec * 1000) / 1000)
        self.timeout = httpx.Timeout(timeout_sec, connect=10.0)
        self._request_slots = (
            request_slots if request_slots is not None else _OPENCODE_REQUEST_SLOTS
        )
        self._orchestrator = agent_orchestrator.AgentOrchestrator(self)

    async def create_session(self, title: str) -> str:
        """创建会话，返回会话 id（AgentEngine 协议形态，engine-09 C3 对齐）。

        A0~B4 返回服务端原始 dict；C3 起按协议（base.AgentEngine）只返回 id，
        与 CodexEngine/PiEngine 形态一致，编排层不再依赖 opencode 私有响应结构。
        """
        for attempt in range(len(_SESSION_CREATE_RETRY_DELAYS_SEC) + 1):
            try:
                async with self._request_slot():
                    async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                        response = await client.post(
                            f"{self.base_url}/session",
                            json={"title": title},
                        )
                        response.raise_for_status()
                        payload = response.json()
                        session_id = str(payload.get("id") or "").strip() if isinstance(payload, dict) else ""
                        if not session_id:
                            raise RuntimeError("futurecode 创建 session 返回缺少 id。")
                        return session_id
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if await self._retry_session_create(exc, attempt):
                    continue
                if isinstance(exc, httpx.TimeoutException):
                    raise RuntimeError(
                        f"futurecode 创建 session 超时（{self.base_url}/session）。"
                    ) from exc
                raise RuntimeError(f"futurecode 创建 session 失败：{self._short_http_error(exc)}") from exc
            except httpx.HTTPStatusError as exc:
                if (
                    exc.response.status_code in _SESSION_CREATE_RETRYABLE_STATUS_CODES
                    and await self._retry_session_create(exc, attempt)
                ):
                    continue
                raise RuntimeError(f"futurecode 创建 session 失败：{self._short_http_error(exc)}") from exc
            except httpx.TimeoutException as exc:
                raise RuntimeError(
                    f"futurecode 创建 session 超时（{self.base_url}/session）。"
                ) from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"futurecode 创建 session 失败：{self._short_http_error(exc)}") from exc
            except ValueError as exc:  # pragma: no cover
                raise RuntimeError("futurecode 创建 session 返回了非 JSON 响应。") from exc

        raise RuntimeError("futurecode 创建 session 失败：重试流程异常结束。")  # pragma: no cover

    @asynccontextmanager
    async def _request_slot(self) -> Any:
        """并发预算闸门（BudgetPool，threading 原语，跨线程/跨循环共享）。

        非阻塞轮询获取：取消落在等待窗口时协程直接退出、不持有许可——
        `asyncio.to_thread(acquire)` 的阻塞等待无法被取消，executor 线程随后
        acquire 成功却无人 release，许可永久泄漏（预算为 1 时进程级挂死）。
        不换 asyncio.Semaphore：它有循环亲和性，引擎实例跨事件循环复用会炸。
        B4（engine-06）后 `self._request_slots` 是从全局预算派生的 `BudgetPool`
        （见 agent_engine/concurrency.py），本方法的获取/释放语义不变。
        """
        while not self._request_slots.acquire(blocking=False):
            await asyncio.sleep(0.1)
        try:
            yield
        finally:
            self._request_slots.release()

    @staticmethod
    async def _retry_session_create(exc: httpx.HTTPError, attempt: int) -> bool:
        if attempt >= len(_SESSION_CREATE_RETRY_DELAYS_SEC):
            return False
        delay = _SESSION_CREATE_RETRY_DELAYS_SEC[attempt]
        logger.warning(
            "futurecode session create transient failure; retrying in %.1fs (attempt %d/%d): %s",
            delay,
            attempt + 1,
            len(_SESSION_CREATE_RETRY_DELAYS_SEC) + 1,
            OpencodeEngine._short_http_error(exc),
        )
        await asyncio.sleep(delay)
        return True

    async def send_prompt(
        self,
        session_id: str,
        prompt_text: str,
        *,
        timeout: httpx.Timeout | None = None,
        tools: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        """发送 prompt（B2：仅「确认未送达」可自动重发，其余显式报错）。

        幂等性取舍：opencode 不支持同会话 message 去重，prompt 一旦送达，
        重发即重复执行。因此只有连接未建立（ConnectError/ConnectTimeout，
        请求字节未写出）才按预算重发；读超时/5xx/连接中途断开等送达状态
        不确定的错误抛 `PromptDeliveryUncertainError`，由上层显式决策。
        """
        payload = {
            "model": {
                "providerID": self.provider_id,
                "modelID": self.model_id,
            },
            "parts": [
                {
                    "type": "text",
                    "text": prompt_text,
                }
            ],
        }
        if tools is not None:
            payload["tools"] = dict(tools)
        max_retries = settings.opencode_send_prompt_max_retries
        backoff = settings.opencode_send_prompt_retry_backoff_sec or (1,)
        for attempt in range(max_retries + 1):
            try:
                # Queue before creating the HTTP client so waiting does not consume the model timeout.
                async with self._request_slot():
                    async with httpx.AsyncClient(timeout=timeout or self.timeout, trust_env=False) as client:
                        response = await client.post(
                            f"{self.base_url}/session/{session_id}/message",
                            json=payload,
                        )
                        response.raise_for_status()
                        if not response.text.strip():
                            raise RuntimeError("futurecode 返回了空响应。")
                        try:
                            return response.json()
                        except ValueError as exc:
                            raw = self._shorten_text(response.text, limit=420)
                            raise RuntimeError(f"futurecode 返回了非 JSON 响应：{raw}") from exc
            except httpx.HTTPError as exc:
                if engine_errors.is_pre_delivery_error(exc):
                    if attempt < max_retries:
                        delay = backoff[min(attempt, len(backoff) - 1)]
                        logger.warning(
                            "futurecode send_prompt 连接未建立（prompt 未送达）；%.1fs 后重发 (attempt %d/%d, session %s): %s",
                            delay,
                            attempt + 1,
                            max_retries + 1,
                            session_id,
                            self._short_http_error(exc),
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise RuntimeError(
                        f"futurecode 生成失败：连接未建立（session {session_id}，已重发 {max_retries} 次）："
                        f"{self._short_http_error(exc)}"
                    ) from exc
                # 送达状态不确定：禁止自动重发（重复执行风险），显式报错保留上下文。
                if isinstance(exc, httpx.TimeoutException):
                    raise engine_errors.PromptDeliveryUncertainError(
                        f"futurecode 生成超时，请缩短输入或稍后重试。"
                        f"（session {session_id}：读超时前 prompt 可能已送达并在执行中，"
                        f"为避免重复执行未自动重发，请检查会话状态后由上层决策）"
                    ) from exc
                raise engine_errors.PromptDeliveryUncertainError(
                    f"futurecode 生成失败：{self._short_http_error(exc)}"
                    f"（session {session_id}：prompt 送达状态不确定，为避免重复执行未自动重发，"
                    f"请检查会话状态后由上层决策）"
                ) from exc

        raise RuntimeError("futurecode 生成失败：重试流程异常结束。")  # pragma: no cover

    async def send_text_prompt(
        self,
        title: str,
        prompt_text: str,
        *,
        tools: dict[str, bool] | None = None,
        keep_session: bool = False,
    ) -> dict[str, Any]:
        """建会话发单条 prompt。`keep_session=False`（默认）终态即删服务端会话（B3）；
        `keep_session=True` 只用于跨轮复用会话的调用方（technical_chat_service 共创对话）。
        """
        session_id = await self.create_session(title)
        try:
            response = (
                await self.send_prompt(session_id, prompt_text)
                if tools is None
                else await self.send_prompt(session_id, prompt_text, tools=tools)
            )
            info = response.get("info") if isinstance(response.get("info"), dict) else {}
            if info.get("error"):
                raise RuntimeError(self._format_response_error(info["error"]))
            return {
                "sessionId": session_id,
                "providerId": self.provider_id,
                "modelId": self.model_id,
                "reply": self.extract_text_response(response),
                "opencodeOutput": self._build_output_trace(session_id, response),
            }
        finally:
            if not keep_session:
                await self.delete_session_quietly(session_id)

    # ------------------------------------------------------------------
    # AgentEngine 协议入口（engine-09 C3 对齐，engine-03 F5 收尾）
    # ------------------------------------------------------------------
    async def run_session(
        self,
        session_id: str,
        prompt_text: str,
        *,
        provider_id: str | None = None,
        model_id: str | None = None,
        tools: dict[str, bool] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
        on_tool_completed: Callable[[ToolCompletedEvent], bool] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> EngineRunResult:
        """协议级「跑一次会话」：内部复用 `_send_prompt_with_session_polling`。

        语义映射：
        - `on_tool_completed` → 最小 EarlyCompletionPlan（in-loop 收割 + 停会话），
          回调可改写 `event.stdout` 作为收割产物（与 codex/pi 引擎同一口径）；
          编排层带完整轮询相位（wait_after_prompt_return 等）的链路仍走
          `_send_prompt_with_session_polling(early_completion=...)`，不经本方法。
        - provider/model 为实例级固定（构造时从系统设置/环境解析），按请求传入
          且与实例不一致时记 warning 忽略；轮询链路不接按请求 tools（同记 warning）。
        - 会话级错误（info.error）显式抛 RuntimeError（协议引擎同为失败即抛）。
        """
        if provider_id and provider_id != self.provider_id:
            logger.warning(
                "opencode 引擎 provider 为实例级固定（%s），run_session(provider_id=%s) 已忽略。",
                self.provider_id,
                provider_id,
            )
        if model_id and model_id != self.model_id:
            logger.warning(
                "opencode 引擎 model 为实例级固定（%s），run_session(model_id=%s) 已忽略。",
                self.model_id,
                model_id,
            )
        if tools:
            logger.warning("opencode 轮询链路不支持按请求 tools 开关，run_session(tools=...) 已忽略。")
        plan = None
        if on_tool_completed is not None:
            plan = EarlyCompletionPlan(
                display_label="tool",
                tool_completed_factory=lambda: on_tool_completed,
                stop_on_early_complete=True,
                stop_label="受控命令提前收割",
                completion_source="tool",
                completion_trace_text="受控命令已完成，后端提前收割其 stdout 作为会话结果。",
            )
        response = await self._send_prompt_with_session_polling(
            session_id,
            prompt_text,
            stream_callback=stream_callback,
            early_completion=plan,
            cancel_check=cancel_check,
        )
        info = response.get("info") if isinstance(response.get("info"), dict) else {}
        if info.get("error"):
            raise RuntimeError(self._format_response_error(info["error"]))
        tool_outputs = list(
            iter_completed_bash_tool_events(await self._best_effort_messages(session_id))
        )
        return EngineRunResult(
            session_id=session_id,
            reply_text=self.extract_text_response(response),
            tool_outputs=tool_outputs,
            trace=self._build_output_trace(session_id, response),
        )

    async def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        """AgentEngine 协议方法（`list_session_messages` 的协议名，旧名保留）。"""
        return await self.list_session_messages(session_id)

    # ------------------------------------------------------------------
    # 业务编排门面（A1）：实现见 agent_engine/orchestrator.py 的 AgentOrchestrator，
    # 方法名与签名保持不动（B1 起为 async）。
    # ------------------------------------------------------------------
    async def generate_outline(self, prompt_text: str) -> dict[str, Any]:
        return await self._orchestrator.generate_outline(prompt_text)

    async def run_outline_decision_session(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._orchestrator.run_outline_decision_session(*args, **kwargs)

    async def generate_outline_with_trace(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._orchestrator.generate_outline_with_trace(*args, **kwargs)

    async def generate_draft_sections(self, prompt_text: str) -> dict[str, Any]:
        return await self._orchestrator.generate_draft_sections(prompt_text)

    async def generate_draft_sections_with_trace(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._orchestrator.generate_draft_sections_with_trace(*args, **kwargs)

    async def run_bid_business_assembler_with_trace(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._orchestrator.run_bid_business_assembler_with_trace(*args, **kwargs)

    async def run_bid_business_format_cleaner_with_trace(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._orchestrator.run_bid_business_format_cleaner_with_trace(*args, **kwargs)

    async def run_bid_tech_gap_planner_with_trace(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._orchestrator.run_bid_tech_gap_planner_with_trace(*args, **kwargs)

    async def run_bid_tech_tag_importer_with_trace(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._orchestrator.run_bid_tech_tag_importer_with_trace(*args, **kwargs)

    async def run_bid_business_gap_planner_with_trace(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._orchestrator.run_bid_business_gap_planner_with_trace(*args, **kwargs)

    async def run_bid_business_table_fill_with_trace(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._orchestrator.run_bid_business_table_fill_with_trace(*args, **kwargs)

    async def run_bid_tech_table_filler_with_trace(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._orchestrator.run_bid_tech_table_filler_with_trace(*args, **kwargs)

    async def run_bid_tech_score_index_xref_with_trace(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._orchestrator.run_bid_tech_score_index_xref_with_trace(*args, **kwargs)

    async def run_bid_tech_fact_curator_with_trace(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._orchestrator.run_bid_tech_fact_curator_with_trace(*args, **kwargs)

    async def generate_wiki_blueprint_with_trace(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._orchestrator.generate_wiki_blueprint_with_trace(*args, **kwargs)

    async def generate_tender_parse_with_trace(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._orchestrator.generate_tender_parse_with_trace(*args, **kwargs)

    async def run_tender_parse_shard_with_trace(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._orchestrator.run_tender_parse_shard_with_trace(*args, **kwargs)

    async def review_business_commitments_with_trace(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._orchestrator.review_business_commitments_with_trace(*args, **kwargs)

    async def review_business_attachment_templates_with_trace(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._orchestrator.review_business_attachment_templates_with_trace(*args, **kwargs)

    async def extract_business_templates_with_trace(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self._orchestrator.extract_business_templates_with_trace(*args, **kwargs)

    # ------------------------------------------------------------------
    # 会话监管与轮询（引擎通用能力，不识业务命令）
    # ------------------------------------------------------------------
    async def list_session_messages(self, session_id: str) -> list[dict[str, Any]]:
        """拉取会话消息（B2 起失败抛异常，不再吞错返回 []）。

        吞错会让「网络断线」与「会话真无消息」不可区分，断线时间被 idle 监管
        误计为模型停滞。需要尽力而为语义的调用方用 `_best_effort_messages`；
        轮询监管链路用 `_poll_session_messages`（断线重连 + 断线耗时上报）。
        """
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=5.0), trust_env=False) as client:
            response = await client.get(f"{self.base_url}/session/{session_id}/message")
            response.raise_for_status()
            payload = response.json()

        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    async def _best_effort_messages(self, session_id: str) -> list[dict[str, Any]]:
        """尽力而为取消息（失败返回 []）：留痕/收尾取证等不允许抛错的路径用。"""
        try:
            return await self.list_session_messages(session_id)
        except (httpx.HTTPError, ValueError):
            return []

    async def _poll_session_messages(
        self,
        session_id: str,
        cancel_check: Callable[[], bool] | None = None,
    ) -> tuple[list[dict[str, Any]], float]:
        """轮询取消息（B2 断线恢复）：可恢复错误按退避重连，不立即判死。

        返回 `(messages, disconnected_seconds)`：`disconnected_seconds` 是本次调用
        花在断线重连上的时长，调用方把它加回 idle 时钟——断线时间不计入 idle，
        「opencode 服务重启」不被误判成「模型 stall」。
        重连预算耗尽抛 `PollReconnectExhaustedError`（显式断线错误）；
        不可恢复错误（4xx/500 等）维持现状语义：返回 `[]` 交给 idle/业务判定。
        """
        try:
            return await self.list_session_messages(session_id), 0.0
        except (httpx.HTTPError, ValueError) as exc:
            if not engine_errors.is_recoverable_poll_error(exc):
                return [], 0.0
            first_error = exc

        disconnected_started = time.monotonic()
        max_attempts = settings.opencode_poll_reconnect_max_attempts
        backoff = settings.opencode_poll_reconnect_backoff_sec or (1,)
        for attempt in range(max_attempts):
            delay = float(backoff[min(attempt, len(backoff) - 1)])
            logger.warning(
                "futurecode 轮询断线；%.1fs 后重连 (attempt %d/%d, session %s): %s",
                delay,
                attempt + 1,
                max_attempts,
                session_id,
                self._short_http_error(first_error),
            )
            # 切片 sleep 保取消响应：断线重连窗口内取消延迟不超过 0.5s。
            remaining = delay
            while remaining > 0:
                if cancel_check is not None and cancel_check():
                    return [], time.monotonic() - disconnected_started
                step = min(0.5, remaining)
                await asyncio.sleep(step)
                remaining -= step
            try:
                messages = await self.list_session_messages(session_id)
                return messages, time.monotonic() - disconnected_started
            except (httpx.HTTPError, ValueError) as exc:
                if not engine_errors.is_recoverable_poll_error(exc):
                    return [], time.monotonic() - disconnected_started
                first_error = exc

        raise engine_errors.PollReconnectExhaustedError(
            f"futurecode 轮询断线重连失败（session {session_id}，已重连 {max_attempts} 次，"
            f"断线约 {int(time.monotonic() - disconnected_started)}s）："
            f"{self._short_http_error(first_error)}。opencode 服务不可达，非模型停滞；"
            f"会话可能仍在服务端运行，请恢复服务后由上层决策重试。"
        ) from first_error

    async def abort_session(self, session_id: str) -> bool:
        session_id = str(session_id or "").strip()
        if not session_id:
            return False
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=5.0), trust_env=False) as client:
                response = await client.post(f"{self.base_url}/session/{session_id}/abort")
                response.raise_for_status()
                if not response.text.strip():
                    return True
                return bool(response.json())
        except (httpx.HTTPError, ValueError):
            return False

    async def delete_session(self, session_id: str) -> None:
        """删除服务端会话（B3，协议方法）：DELETE /session/{id}。

        404 幂等（会话已不存在视为回收成功）；其余失败显式抛错不吞。
        终态回收路径用 `delete_session_quietly`（失败只告警不阻断主流程）。
        """
        session_id = str(session_id or "").strip()
        if not session_id:
            return
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=5.0), trust_env=False) as client:
                response = await client.delete(f"{self.base_url}/session/{session_id}")
            if response.status_code == 404:
                return
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"futurecode 删除 session 失败（{session_id}）：{self._short_http_error(exc)}"
            ) from exc

    async def delete_session_quietly(self, session_id: str) -> None:
        """终态回收入口（harness-04）：回收失败只告警，不阻断主流程。"""
        try:
            await self.delete_session(session_id)
        except Exception as exc:  # noqa: BLE001 - 回收失败不掩盖业务结果
            logger.warning("futurecode session %s 回收失败（不阻断主流程）：%s", session_id, exc)

    @staticmethod
    async def _wait_worker_stop(worker_task: asyncio.Task[None], timeout: float) -> bool:
        """等发送 prompt 的 asyncio task 收尾（对齐原 `thread.join(timeout)` 语义）。"""
        try:
            await asyncio.wait_for(asyncio.shield(worker_task), timeout)
            return True
        except TimeoutError:
            return False

    async def _stop_session_after_early_completion(
        self,
        session_id: str,
        *,
        finished: asyncio.Task[None] | None = None,
        command_label: str,
    ) -> None:
        """提前收割后停掉会话；`command_label` 由业务计划注入（报错文案的一部分）。"""
        aborted = await self.abort_session(session_id)
        if finished is not None:
            if await self._wait_worker_stop(finished, OPENCODE_EARLY_COMPLETION_STOP_TIMEOUT_SECONDS):
                return
            status = "已发送 abort" if aborted else "abort 失败"
            raise RuntimeError(f"{command_label} 后 Opencode worker 未停止（{status}）。")
        if not aborted:
            raise RuntimeError(f"{command_label} 后无法确认 Opencode session 已停止。")

    async def _send_prompt_with_session_polling(
        self,
        session_id: str,
        prompt_text: str,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
        *,
        early_completion: EarlyCompletionPlan | None = None,
        cancel_check: Callable[[], bool] | None = None,
        assistant_stop_validator: Callable[[], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if stream_callback is None and early_completion is None:
            return await self.send_prompt(session_id, prompt_text)

        response_holder: dict[str, Any] = {}
        error_holder: dict[str, Exception] = {}
        abort_sent = False
        # 每个相位各取一个完成判定回调（业务侧可按相位独立维护去重状态）。
        tool_completed = (
            early_completion.tool_completed_factory()
            if early_completion is not None and early_completion.tool_completed_factory is not None
            else None
        )

        idle_timeout = self._session_polling_idle_timeout()
        # 轮询监管的长任务：阻塞 message 请求的读超时不得短于轮询 idle 监管时限。
        # 系统设置的 timeoutMs（默认 30s）若直接作用于这里，脚本/生成阶段 HTTP 层先超时，
        # 后端 400 返回而 futurecode 会话仍在后台运行，产物（如事实表建议文件）无人回收。
        configured_read = float(self.timeout.read or 0.0)
        run_timeout = httpx.Timeout(max(configured_read, idle_timeout + 60.0), connect=10.0)

        async def worker() -> None:
            # 原 daemon 线程的 asyncio task 形态：异常收进 error_holder 由主协程抛出，
            # task 自身不携带未消费异常（不会「静默死亡」）。
            try:
                response_holder["response"] = await self.send_prompt(session_id, prompt_text, timeout=run_timeout)
            except Exception as exc:  # pragma: no cover - exercised via caller path
                error_holder["error"] = exc

        worker_task = asyncio.create_task(
            worker(),
            name=f"opencode-message-{session_id}",
        )

        async def raise_if_cancelled() -> None:
            nonlocal abort_sent
            if cancel_check is None or not cancel_check():
                return
            if not abort_sent:
                abort_sent = True
                await self.abort_session(session_id)
            # 取消路径显式收割发送 task（原 daemon 线程会被遗弃到请求自然结束）。
            worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task
            raise ParseCancelledError("解析已取消。")

        command_label = early_completion.display_label if early_completion is not None else ""
        progress_started_at = time.monotonic()
        last_signature: tuple[str, tuple[tuple[str, str], ...]] | None = None
        last_activity = progress_started_at
        last_heartbeat = last_activity
        heartbeat_index = 0

        def apply_disconnect(disconnected: float) -> None:
            # 断线时间不计入 idle：重连耗时加回活动/心跳时钟，
            # 「opencode 服务重启」不被误判成「模型 stall」。
            nonlocal last_activity, last_heartbeat
            if disconnected > 0:
                last_activity += disconnected
                last_heartbeat += disconnected

        while not await self._wait_worker_stop(worker_task, 0.5):
            await raise_if_cancelled()
            previous_signature = last_signature
            messages, disconnected = await self._poll_session_messages(session_id, cancel_check)
            apply_disconnect(disconnected)
            snapshot = self._get_session_output_snapshot_from_messages(session_id, messages)
            if stream_callback is not None:
                last_signature = self._emit_session_output_delta_from_snapshot(
                    session_id,
                    snapshot,
                    stream_callback,
                    last_signature,
                    elapsed_seconds=time.monotonic() - progress_started_at,
                )
            elif early_completion is not None:
                signature = snapshot.get("signature")
                if signature is not None:
                    last_signature = signature
            if last_signature != previous_signature:
                last_activity = time.monotonic()
                last_heartbeat = last_activity
                heartbeat_index = 0
            else:
                now = time.monotonic()
                if (
                    stream_callback is not None
                    and now - last_heartbeat >= OPENCODE_PROGRESS_HEARTBEAT_SECONDS
                ):
                    heartbeat_index += 1
                    self._emit_session_progress_heartbeat(
                        session_id=session_id,
                        stream_callback=stream_callback,
                        snapshot=snapshot,
                        idle_seconds=now - last_activity,
                        elapsed_seconds=now - progress_started_at,
                        heartbeat_index=heartbeat_index,
                        early_tool_command=command_label,
                    )
                    last_heartbeat = now
                if now - last_activity > idle_timeout:
                    if not abort_sent:
                        abort_sent = True
                        aborted = await self.abort_session(session_id)
                    else:
                        aborted = True
                    if not await self._wait_worker_stop(worker_task, OPENCODE_EARLY_COMPLETION_STOP_TIMEOUT_SECONDS):
                        abort_status = "已发送 abort" if aborted else "abort 失败"
                        raise RuntimeError(
                            "futurecode idle timeout 后 Opencode worker 未停止"
                            f"（{abort_status}），请检查 session {session_id}。"
                        )
                    if early_completion is not None and early_completion.on_idle_stalled is not None:
                        early_completion.on_idle_stalled(
                            session_id,
                            await self._best_effort_messages(session_id),
                            idle_timeout,
                        )
                    raise RuntimeError(
                        f"futurecode idle timeout after {int(idle_timeout)} seconds without new output; "
                        f"check session {session_id} tool calls."
                    )
            if early_completion is not None and tool_completed is not None:
                messages, disconnected = await self._poll_session_messages(session_id, cancel_check)
                apply_disconnect(disconnected)
                self._raise_session_error_if_present(session_id, messages)
                completed_event = self._find_early_completion_event(messages, tool_completed)
                if completed_event is not None:
                    if early_completion.stop_on_early_complete:
                        await self._stop_session_after_early_completion(
                            session_id,
                            finished=worker_task,
                            command_label=early_completion.stop_label,
                        )
                    return self._early_completion_response(
                        session_id=session_id,
                        messages=messages,
                        output=early_completion.harvest_payload(completed_event),
                        trace_text=early_completion.completion_trace_text,
                        completion_source=early_completion.completion_source,
                        stream_callback=stream_callback,
                        elapsed_seconds=(
                            time.monotonic() - progress_started_at
                            if early_completion.include_elapsed_in_loop
                            else None
                        ),
                    )
            if early_completion is not None and early_completion.on_assistant_stopped is not None:
                messages, disconnected = await self._poll_session_messages(session_id, cancel_check)
                apply_disconnect(disconnected)
                if self._session_messages_show_assistant_stop(messages):
                    await self._stop_session_after_early_completion(
                        session_id,
                        finished=worker_task,
                        command_label=early_completion.stop_label,
                    )
                    return self._early_completion_response(
                        session_id=session_id,
                        messages=messages,
                        output=early_completion.on_assistant_stopped(),
                        trace_text=early_completion.assistant_stop_trace_text,
                        completion_source=early_completion.assistant_stop_completion_source,
                        stream_callback=stream_callback,
                    )
            if assistant_stop_validator is not None:
                messages, disconnected = await self._poll_session_messages(session_id, cancel_check)
                apply_disconnect(disconnected)
                self._raise_session_error_if_present(session_id, messages)
                if self._session_messages_show_assistant_stop(messages):
                    await self.abort_session(session_id)
                    if not await self._wait_worker_stop(worker_task, OPENCODE_EARLY_COMPLETION_STOP_TIMEOUT_SECONDS):
                        raise RuntimeError(
                            "OpenCode assistant 已完成接力会话，但消息请求未在 abort 后停止。"
                        )
                    validated = assistant_stop_validator()
                    snapshot = self._get_session_output_snapshot_from_messages(
                        session_id,
                        messages,
                    )
                    trace_parts = list(snapshot.get("parts") or [])
                    trace_parts.append(
                        {
                            "type": "text",
                            "text": "OpenCode 已完成本次决策单元，后端校验持久化进度后继续下一会话。",
                        }
                    )
                    early_response = self._tool_output_response(
                        session_id=session_id,
                        output=json.dumps(validated, ensure_ascii=False),
                        trace_parts=trace_parts,
                    )
                    early_response["_completionSource"] = "assistant-stop-validator"
                    early_response["_assistantStopValidation"] = validated
                    return early_response

        if early_completion is not None and early_completion.wait_after_prompt_return:
            messages, _ = await self._poll_session_messages(session_id, cancel_check)
            self._raise_session_error_if_present(session_id, messages)
            tool_completed = (
                early_completion.tool_completed_factory()
                if early_completion.tool_completed_factory is not None
                else None
            )
            if early_completion.grace_wait_running_tool and tool_completed is not None:
                completed_event = self._find_early_completion_event(messages, tool_completed)
                if completed_event is not None:
                    return self._early_completion_response(
                        session_id=session_id,
                        messages=messages,
                        output=early_completion.harvest_payload(completed_event),
                        trace_text=early_completion.immediate_trace_text,
                        completion_source=early_completion.completion_source,
                        stream_callback=stream_callback,
                    )
                if self._last_tool_is_running(self._last_tool_trace(messages)):
                    stalled_until = time.monotonic() + idle_timeout
                    last_signature = self._get_session_output_snapshot_from_messages(session_id, messages).get("signature")
                    last_activity = 0.0
                    last_heartbeat = 0.0
                    if stream_callback is not None:
                        last_activity = time.monotonic()
                        last_heartbeat = last_activity
                    heartbeat_index = 0
                    while time.monotonic() < stalled_until:
                        await raise_if_cancelled()
                        await asyncio.sleep(0.5)
                        messages, disconnected = await self._poll_session_messages(session_id, cancel_check)
                        apply_disconnect(disconnected)
                        if disconnected > 0:
                            stalled_until += disconnected
                        self._raise_session_error_if_present(session_id, messages)
                        completed_event = self._find_early_completion_event(messages, tool_completed)
                        if completed_event is not None:
                            return self._early_completion_response(
                                session_id=session_id,
                                messages=messages,
                                output=early_completion.harvest_payload(completed_event),
                                trace_text=early_completion.immediate_trace_text,
                                completion_source=early_completion.completion_source,
                                stream_callback=stream_callback,
                                elapsed_seconds=time.monotonic() - progress_started_at,
                            )
                        snapshot = self._get_session_output_snapshot_from_messages(session_id, messages)
                        signature = snapshot.get("signature")
                        if signature != last_signature:
                            stalled_until = time.monotonic() + idle_timeout
                            last_signature = signature
                            heartbeat_index = 0
                            if stream_callback is not None:
                                last_activity = time.monotonic()
                                last_heartbeat = last_activity
                            if stream_callback is not None:
                                stream_callback(
                                    {
                                        "status": snapshot["status"],
                                        "sessionId": session_id,
                                        "providerId": self.provider_id,
                                        "modelId": self.model_id,
                                        "receivedAt": snapshot["receivedAt"],
                                        "parts": snapshot["parts"],
                                        "elapsedSeconds": max(0, int(time.monotonic() - progress_started_at)),
                                    }
                                )
                        elif stream_callback is not None:
                            now = time.monotonic()
                            if now - last_heartbeat >= OPENCODE_PROGRESS_HEARTBEAT_SECONDS:
                                heartbeat_index += 1
                                self._emit_session_progress_heartbeat(
                                    session_id=session_id,
                                    stream_callback=stream_callback,
                                    snapshot=snapshot,
                                    idle_seconds=now - last_activity,
                                    elapsed_seconds=now - progress_started_at,
                                    heartbeat_index=heartbeat_index,
                                    early_tool_command=command_label,
                                )
                                last_heartbeat = now
                        if not self._last_tool_is_running(self._last_tool_trace(messages)):
                            break
                    if self._last_tool_is_running(self._last_tool_trace(messages)):
                        if early_completion.on_idle_stalled is not None:
                            early_completion.on_idle_stalled(session_id, messages, idle_timeout)
                        raise RuntimeError(
                            f"futurecode idle timeout after {int(idle_timeout)} seconds without new output; "
                            f"check session {session_id} tool calls."
                        )

            pending_response = await self._wait_for_early_completion_after_prompt_return(
                session_id=session_id,
                idle_timeout=idle_timeout,
                stream_callback=stream_callback,
                cancel_check=cancel_check,
                progress_started_at=progress_started_at,
                plan=early_completion,
            )
            if pending_response:
                return pending_response

        if stream_callback is not None:
            await raise_if_cancelled()
            self._raise_session_error_if_present(session_id, await self._best_effort_messages(session_id))
            last_signature = await self._emit_session_output_delta(
                session_id,
                stream_callback,
                last_signature,
                elapsed_seconds=time.monotonic() - progress_started_at,
            )
        await worker_task
        await raise_if_cancelled()
        if error_holder.get("error"):
            raise error_holder["error"]
        return response_holder["response"]

    async def _wait_for_early_completion_after_prompt_return(
        self,
        *,
        session_id: str,
        idle_timeout: float,
        stream_callback: Callable[[dict[str, Any]], None] | None,
        cancel_check: Callable[[], bool] | None = None,
        progress_started_at: float | None = None,
        plan: EarlyCompletionPlan,
    ) -> dict[str, Any] | None:
        """三套 `_wait_for_*_finalize` 收敛后的通用「等命令完成」。

        差异点（terminal 判定、stall trace 文案、stalled 异常、收割后是否停会话）
        全部由 `plan` 注入；本方法不识任何业务命令。
        """
        tool_completed = (
            plan.tool_completed_factory() if plan.tool_completed_factory is not None else None
        )
        messages: list[dict[str, Any]] = []
        last_signature: tuple[str, tuple[tuple[str, str], ...]] | None = None
        deadline = time.monotonic() + idle_timeout
        if progress_started_at is None:
            progress_started_at = time.monotonic()
        last_activity = 0.0
        last_heartbeat = 0.0
        if stream_callback is not None:
            last_activity = time.monotonic()
            last_heartbeat = last_activity
        heartbeat_index = 0

        while time.monotonic() < deadline:
            if cancel_check is not None and cancel_check():
                await self.abort_session(session_id)
                raise ParseCancelledError("解析已取消。")
            messages, disconnected = await self._poll_session_messages(session_id, cancel_check)
            if disconnected > 0:
                # 断线时间不计入 idle/deadline：服务重启不被误判成模型 stall。
                deadline += disconnected
                last_activity += disconnected
                last_heartbeat += disconnected
            self._raise_session_error_if_present(session_id, messages)
            completed_event = (
                self._find_early_completion_event(messages, tool_completed)
                if tool_completed is not None
                else None
            )
            if completed_event is not None:
                if plan.stop_on_early_complete:
                    await self._stop_session_after_early_completion(
                        session_id,
                        command_label=plan.stop_label,
                    )
                return self._early_completion_response(
                    session_id=session_id,
                    messages=messages,
                    output=plan.harvest_payload(completed_event),
                    trace_text=plan.post_return_trace_text,
                    completion_source=plan.completion_source,
                    stream_callback=stream_callback,
                    elapsed_seconds=time.monotonic() - progress_started_at,
                )
            if plan.on_assistant_stopped is not None and self._session_messages_show_assistant_stop(messages):
                return self._early_completion_response(
                    session_id=session_id,
                    messages=messages,
                    output=plan.on_assistant_stopped(),
                    trace_text=plan.assistant_stop_trace_text,
                    completion_source=plan.assistant_stop_completion_source,
                    stream_callback=stream_callback,
                    elapsed_seconds=time.monotonic() - progress_started_at,
                )

            snapshot = self._get_session_output_snapshot_from_messages(session_id, messages)
            signature = snapshot.get("signature")
            if signature != last_signature:
                last_signature = signature
                deadline = time.monotonic() + idle_timeout
                heartbeat_index = 0
                if stream_callback is not None:
                    last_activity = time.monotonic()
                    last_heartbeat = last_activity
                if stream_callback is not None:
                    stream_callback(
                        {
                            "status": snapshot["status"],
                            "sessionId": session_id,
                            "providerId": self.provider_id,
                            "modelId": self.model_id,
                            "receivedAt": snapshot["receivedAt"],
                            "parts": snapshot["parts"],
                            "elapsedSeconds": max(0, int(time.monotonic() - progress_started_at)),
                        }
                    )
            elif stream_callback is not None:
                now = time.monotonic()
                if now - last_heartbeat >= OPENCODE_PROGRESS_HEARTBEAT_SECONDS:
                    heartbeat_index += 1
                    self._emit_session_progress_heartbeat(
                        session_id=session_id,
                        stream_callback=stream_callback,
                        snapshot=snapshot,
                        idle_seconds=now - last_activity,
                        elapsed_seconds=now - progress_started_at,
                        heartbeat_index=heartbeat_index,
                        early_tool_command=plan.display_label,
                    )
                    last_heartbeat = now
            await asyncio.sleep(0.5)

        if plan.on_idle_stalled is not None:
            plan.on_idle_stalled(session_id, messages, idle_timeout)
        return None

    @staticmethod
    def _find_early_completion_event(
        messages: list[dict[str, Any]],
        on_tool_completed: Callable[[ToolCompletedEvent], bool],
    ) -> ToolCompletedEvent | None:
        """把「已完成 bash 工具」事件逐个交给业务回调；回调判 True 即收割该事件。"""
        for event in iter_completed_bash_tool_events(messages):
            if on_tool_completed(event):
                return event
        return None

    def _early_completion_response(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
        output: str,
        trace_text: str,
        completion_source: str,
        stream_callback: Callable[[dict[str, Any]], None] | None,
        elapsed_seconds: float | None = None,
    ) -> dict[str, Any]:
        snapshot = self._get_session_output_snapshot_from_messages(session_id, messages)
        trace_parts = list(snapshot.get("parts") or [])
        trace_parts.append(
            {
                "type": "text",
                "text": trace_text,
            }
        )
        early_response = self._tool_output_response(
            session_id=session_id,
            output=output,
            trace_parts=trace_parts,
        )
        early_response["_completionSource"] = completion_source
        if stream_callback is not None:
            payload: dict[str, Any] = {
                "status": "received",
                "sessionId": session_id,
                "providerId": self.provider_id,
                "modelId": self.model_id,
                "receivedAt": early_response["_traceReceivedAt"],
                "parts": self._normalize_output_parts(trace_parts),
                "earlyCompletion": True,
                "completionSource": completion_source,
            }
            if elapsed_seconds is not None:
                payload["elapsedSeconds"] = max(0, int(elapsed_seconds))
            stream_callback(payload)
        return early_response

    async def _emit_session_output_delta(
        self,
        session_id: str,
        stream_callback: Callable[[dict[str, Any]], None],
        last_signature: tuple[str, tuple[tuple[str, str], ...]] | None,
        *,
        elapsed_seconds: float | None = None,
    ) -> tuple[str, tuple[tuple[str, str], ...]] | None:
        snapshot = await self._get_session_output_snapshot(session_id)
        return self._emit_session_output_delta_from_snapshot(
            session_id,
            snapshot,
            stream_callback,
            last_signature,
            elapsed_seconds=elapsed_seconds,
        )

    def _emit_session_output_delta_from_snapshot(
        self,
        session_id: str,
        snapshot: dict[str, Any],
        stream_callback: Callable[[dict[str, Any]], None],
        last_signature: tuple[str, tuple[tuple[str, str], ...]] | None,
        *,
        elapsed_seconds: float | None = None,
    ) -> tuple[str, tuple[tuple[str, str], ...]] | None:
        signature = snapshot.get("signature")
        if signature is None or signature == last_signature:
            return last_signature

        payload = {
            "status": snapshot["status"],
            "sessionId": session_id,
            "providerId": self.provider_id,
            "modelId": self.model_id,
            "receivedAt": snapshot["receivedAt"],
            "parts": snapshot["parts"],
        }
        if elapsed_seconds is not None:
            payload["elapsedSeconds"] = max(0, int(elapsed_seconds))
        stream_callback(payload)
        return signature

    def _emit_session_progress_heartbeat(
        self,
        *,
        session_id: str,
        stream_callback: Callable[[dict[str, Any]], None],
        snapshot: dict[str, Any],
        idle_seconds: float,
        elapsed_seconds: float | None = None,
        heartbeat_index: int,
        early_tool_command: str = "",
    ) -> None:
        resolved_idle_seconds = max(1, int(idle_seconds))
        resolved_elapsed_seconds = (
            max(resolved_idle_seconds, int(elapsed_seconds))
            if elapsed_seconds is not None
            else resolved_idle_seconds
        )
        stream_callback(
            {
                "status": snapshot.get("status") or "waiting",
                "sessionId": session_id,
                "providerId": self.provider_id,
                "modelId": self.model_id,
                "receivedAt": snapshot.get("receivedAt") or "",
                "parts": snapshot.get("parts") or [],
                "heartbeat": True,
                "heartbeatIndex": heartbeat_index,
                "idleSeconds": resolved_idle_seconds,
                "elapsedSeconds": resolved_elapsed_seconds,
                "earlyToolCommand": early_tool_command,
            }
        )

    async def _get_session_output_snapshot(self, session_id: str) -> dict[str, Any]:
        return self._get_session_output_snapshot_from_messages(
            session_id,
            await self._best_effort_messages(session_id),
        )

    def _get_session_output_snapshot_from_messages(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        assistant_message: dict[str, Any] | None = None
        fallback_assistant: dict[str, Any] | None = None
        for message in reversed(messages):
            info = message.get("info") or {}
            if str(info.get("role") or "") == "assistant":
                if fallback_assistant is None:
                    fallback_assistant = message
                if message.get("parts"):
                    assistant_message = message
                    break

        if assistant_message is None:
            assistant_message = fallback_assistant

        if assistant_message is None:
            return {
                "status": "waiting",
                "receivedAt": "",
                "parts": [],
                "signature": None,
            }

        info = assistant_message.get("info") or {}
        raw_time = info.get("time") or {}
        received_at = self._coerce_timestamp(
            raw_time.get("completed") if isinstance(raw_time, dict) else raw_time
        )
        parts = self._normalize_output_parts(assistant_message.get("parts") or [])
        assistant_message_id = str(info.get("id") or "")
        return {
            "status": "streaming" if parts else "waiting",
            "receivedAt": received_at,
            "parts": parts,
            "signature": (
                assistant_message_id,
                tuple((str(part.get("type") or ""), str(part.get("text") or "")) for part in parts),
            ),
        }

    def _session_error_trace(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        for message in reversed(messages):
            info = message.get("info") if isinstance(message.get("info"), dict) else {}
            error = info.get("error") if isinstance(info.get("error"), dict) else {}
            if not error:
                continue
            data = error.get("data") if isinstance(error.get("data"), dict) else {}
            message_text = str(data.get("message") or error.get("message") or error.get("name") or "").strip()
            status_code = data.get("statusCode") or data.get("status_code") or ""
            provider_id = str(info.get("providerID") or self.provider_id)
            model_id = str(info.get("modelID") or self.model_id)
            failure_reason = "opencode session error"
            if status_code:
                failure_reason = f"{failure_reason} {status_code}"
            if message_text:
                failure_reason = f"{failure_reason}: {message_text}"
            return {
                "status": "error",
                "sessionId": str(info.get("sessionID") or session_id),
                "providerId": provider_id,
                "modelId": model_id,
                "receivedAt": self._coerce_timestamp((info.get("time") or {}).get("completed") if isinstance(info.get("time"), dict) else ""),
                "parts": [],
                "agentStatus": "error",
                "errorName": str(error.get("name") or ""),
                "errorStatusCode": status_code,
                "failureReason": failure_reason,
                **self._last_tool_trace(messages),
            }
        return {}

    def _raise_session_error_if_present(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> None:
        trace = self._session_error_trace(session_id, messages)
        if not trace:
            return
        error = RuntimeError(str(trace.get("failureReason") or "opencode session error"))
        setattr(error, "opencode_trace", trace)
        raise error

    @staticmethod
    def _last_tool_trace(messages: list[dict[str, Any]]) -> dict[str, Any]:
        for message in reversed(messages):
            message_info = message.get("info") if isinstance(message.get("info"), dict) else {}
            for part in reversed(message.get("parts") or []):
                if not isinstance(part, dict) or str(part.get("type") or "") != "tool":
                    continue
                state = part.get("state") if isinstance(part.get("state"), dict) else {}
                raw_input = state.get("input") if isinstance(state.get("input"), dict) else {}
                return {
                    "lastTool": str(part.get("tool") or ""),
                    "lastToolStatus": str(state.get("status") or ""),
                    "lastToolInput": raw_input,
                    "lastMessageId": str(message_info.get("id") or part.get("id") or ""),
                }
        return {}

    @staticmethod
    def _last_tool_is_running(trace: dict[str, Any]) -> bool:
        if not trace:
            return False
        return str(trace.get("lastToolStatus") or "").lower() in {"running", "pending", "started"}

    @staticmethod
    def _session_messages_show_assistant_stop(messages: list[dict[str, Any]]) -> bool:
        for message in reversed(messages):
            info = message.get("info") if isinstance(message.get("info"), dict) else {}
            if str(info.get("role") or "") != "assistant":
                continue
            if str(info.get("finish") or "").strip().lower() != "stop":
                return False
            return not OpencodeEngine._last_tool_is_running(OpencodeEngine._last_tool_trace(messages))
        return False

    @staticmethod
    def _session_polling_idle_timeout(early_tool_command: str = "") -> float:
        # early_tool_command 形参仅为兼容保留（现状从不区分命令取值），A1 后不传。
        timeout = max(120.0, min(float(settings.opencode_timeout_sec), 900.0))
        return timeout

    def _build_tool_stalled_trace(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
        idle_timeout: float,
        command_label: str,
    ) -> dict[str, Any]:
        snapshot = self._get_session_output_snapshot_from_messages(session_id, messages)
        last_tool = self._last_tool_trace(messages)
        failure_reason = (
            f"opencode incomplete/stalled: session {session_id} did not complete {command_label} "
            f"within {int(idle_timeout)} seconds."
        )
        return {
            "status": "stalled",
            "sessionId": session_id,
            "providerId": self.provider_id,
            "modelId": self.model_id,
            "receivedAt": snapshot.get("receivedAt") or self._coerce_timestamp(None),
            "parts": snapshot.get("parts") or [],
            "agentStatus": "stalled",
            "failureReason": failure_reason,
            **last_tool,
        }

    def _tool_output_response(
        self,
        *,
        session_id: str,
        output: str,
        trace_parts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        received_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        return {
            "info": {
                "role": "assistant",
                "providerID": self.provider_id,
                "modelID": self.model_id,
                "time": {"completed": received_at},
                "id": f"{session_id}:tool-output",
            },
            "parts": [{"type": "text", "text": output}],
            "_traceParts": trace_parts,
            "_traceReceivedAt": received_at,
            "_earlyCompletion": True,
        }

    @staticmethod
    def extract_text_response(response: dict[str, Any]) -> str:
        info = response.get("info") if isinstance(response.get("info"), dict) else {}
        if info.get("error"):
            return OpencodeEngine._format_response_error(info["error"])
        text_parts = [
            str(part.get("text") or part.get("reasoning") or "").strip()
            for part in response.get("parts") or []
            if isinstance(part, dict) and str(part.get("type") or "") == "text"
        ]
        if text_parts:
            return "\n".join(part for part in text_parts if part).strip()
        reasoning_parts = [
            str(part.get("reasoning") or "").strip()
            for part in response.get("parts") or []
            if isinstance(part, dict) and str(part.get("type") or "") == "reasoning"
        ]
        return "\n".join(part for part in reasoning_parts if part).strip()

    @staticmethod
    def _shorten_text(value: str, limit: int = 420) -> str:
        text = str(value).strip().replace("\n", " ")
        if len(text) <= limit:
            return text
        return f"{text[:limit - 3]}..."
