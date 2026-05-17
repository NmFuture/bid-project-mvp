from __future__ import annotations

import json
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import httpx

from app.core.config import settings
from app.services.system_settings import system_settings_service


class OpencodeClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
        timeout_ms: int | float | None = None,
    ) -> None:
        config = system_settings_service.get_opencode_model_config_sync()
        self.base_url = str(base_url or config.get("opencodeBaseUrl") or settings.opencode_base_url).rstrip("/")
        self.provider_id = str(provider_id or config.get("providerId") or settings.opencode_provider_id)
        self.model_id = str(model_id or config.get("modelId") or config.get("model") or settings.opencode_model_id)
        raw_timeout_ms = timeout_ms if timeout_ms is not None else config.get("timeoutMs")
        timeout_sec = max(1.0, float(raw_timeout_ms or settings.opencode_timeout_sec * 1000) / 1000)
        self.timeout = httpx.Timeout(timeout_sec, connect=10.0)

    def create_session(self, title: str) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/session",
                    json={"title": title},
                )
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"futurecode 创建 session 超时（{self.base_url}/session）。"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"futurecode 创建 session 失败：{self._short_http_error(exc)}") from exc

        except ValueError as exc:  # pragma: no cover
            raise RuntimeError("futurecode 创建 session 返回了非 JSON 响应。") from exc

    def send_prompt(self, session_id: str, prompt_text: str) -> dict[str, Any]:
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
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
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
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                "futurecode 生成超时，请缩短输入或稍后重试。"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"futurecode 生成失败：{self._short_http_error(exc)}") from exc

    def send_text_prompt(self, title: str, prompt_text: str) -> dict[str, Any]:
        session = self.create_session(title)
        session_id = str(session.get("id") or "")
        response = self.send_prompt(session_id, prompt_text)
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

    def generate_outline(self, prompt_text: str) -> dict[str, Any]:
        result = self.generate_outline_with_trace(prompt_text)
        return {
            "summary": result.get("summary"),
            "nodes": result.get("nodes"),
        }

    def generate_outline_with_trace(
        self,
        prompt_text: str,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
        early_tool_command: str = "s2toc",
    ) -> dict[str, Any]:
        session = self.create_session("S2 目录生成")
        session_id = str(session.get("id") or "")
        if session_ready_callback:
            session_ready_callback(
                {
                    "sessionId": session_id,
                    "providerId": self.provider_id,
                    "modelId": self.model_id,
                }
            )
        response = self._send_prompt_with_session_polling(
            session_id,
            prompt_text,
            stream_callback=stream_callback,
            early_tool_command=early_tool_command,
        )
        parsed = self._extract_outline_json(response)
        return {
            **parsed,
            "opencodeOutput": self._build_output_trace(session_id, response),
        }

    def generate_draft_sections(self, prompt_text: str) -> dict[str, Any]:
        result = self.generate_draft_sections_with_trace(prompt_text)
        return {
            "summary": result.get("summary"),
            "sections": result.get("sections"),
        }

    def generate_draft_sections_with_trace(
        self,
        prompt_text: str,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        session = self.create_session("S4 生成标书")
        session_id = str(session.get("id") or "")
        if session_ready_callback:
            session_ready_callback(
                {
                    "sessionId": session_id,
                    "providerId": self.provider_id,
                    "modelId": self.model_id,
                }
            )
        response = self._send_prompt_with_session_polling(
            session_id,
            prompt_text,
            stream_callback=stream_callback,
        )
        parsed = self._extract_sections_json(response)
        return {
            **parsed,
            "opencodeOutput": self._build_output_trace(session_id, response),
        }

    def run_bid_tech_assembler_with_trace(
        self,
        prompt_text: str,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        session = self.create_session("S4 技术标正文拼装")
        session_id = str(session.get("id") or "")
        if session_ready_callback:
            session_ready_callback(
                {
                    "sessionId": session_id,
                    "providerId": self.provider_id,
                    "modelId": self.model_id,
                }
            )
        response = self._send_prompt_with_session_polling(
            session_id,
            prompt_text,
            stream_callback=stream_callback,
        )
        parsed = self._extract_assembly_json(response)
        return {
            **parsed,
            "opencodeOutput": self._build_output_trace(session_id, response),
        }

    def run_bid_business_assembler_with_trace(
        self,
        prompt_text: str,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        session = self.create_session("S4 商务标响应文件装配")
        session_id = str(session.get("id") or "")
        if session_ready_callback:
            session_ready_callback(
                {
                    "sessionId": session_id,
                    "providerId": self.provider_id,
                    "modelId": self.model_id,
                }
            )
        response = self._send_prompt_with_session_polling(
            session_id,
            prompt_text,
            stream_callback=stream_callback,
            early_tool_command="businessassemble",
        )
        parsed = self._extract_assembly_json(response)
        return {
            **parsed,
            "opencodeOutput": self._build_output_trace(session_id, response),
        }

    def run_bid_business_format_cleaner_with_trace(
        self,
        prompt_text: str,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        session = self.create_session("S4 商务标格式规范化")
        session_id = str(session.get("id") or "")
        if session_ready_callback:
            session_ready_callback(
                {
                    "sessionId": session_id,
                    "providerId": self.provider_id,
                    "modelId": self.model_id,
                }
            )
        response = self._send_prompt_with_session_polling(
            session_id,
            prompt_text,
            stream_callback=stream_callback,
            early_tool_command="businessformat",
        )
        parsed = self._extract_business_format_json(response)
        return {
            **parsed,
            "opencodeOutput": self._build_output_trace(session_id, response),
        }

    def run_bid_tech_gap_planner_with_trace(
        self,
        prompt_text: str,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        session = self.create_session("S3 技术标缺口识别")
        session_id = str(session.get("id") or "")
        if session_ready_callback:
            session_ready_callback(
                {
                    "sessionId": session_id,
                    "providerId": self.provider_id,
                    "modelId": self.model_id,
                }
            )
        response = self._send_prompt_with_session_polling(
            session_id,
            prompt_text,
            stream_callback=stream_callback,
            early_tool_command="s4gap",
        )
        parsed = self._extract_gap_plan_json(response)
        return {
            **parsed,
            "opencodeOutput": self._build_output_trace(session_id, response),
        }

    def run_bid_business_gap_planner_with_trace(
        self,
        prompt_text: str,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        session = self.create_session("S3 商务标缺口处理")
        session_id = str(session.get("id") or "")
        if session_ready_callback:
            session_ready_callback(
                {
                    "sessionId": session_id,
                    "providerId": self.provider_id,
                    "modelId": self.model_id,
                }
            )
        response = self._send_prompt_with_session_polling(
            session_id,
            prompt_text,
            stream_callback=stream_callback,
            early_tool_command="businessgap",
        )
        parsed = self._extract_gap_plan_json(response)
        return {
            **parsed,
            "opencodeOutput": self._build_output_trace(session_id, response),
        }

    def run_bid_tech_table_filler_with_trace(
        self,
        prompt_text: str,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
        early_tool_command: str = "",
    ) -> dict[str, Any]:
        session = self.create_session("S4 技术标缺口 AI 填写")
        session_id = str(session.get("id") or "")
        if session_ready_callback:
            session_ready_callback(
                {
                    "sessionId": session_id,
                    "providerId": self.provider_id,
                    "modelId": self.model_id,
                }
            )
        response = self._send_prompt_with_session_polling(
            session_id,
            prompt_text,
            stream_callback=stream_callback,
            early_tool_command=early_tool_command,
        )
        parsed = self._extract_table_fill_json(response)
        return {
            **parsed,
            "opencodeOutput": self._build_output_trace(session_id, response),
        }

    def generate_wiki_blueprint_with_trace(
        self,
        prompt_text: str,
        session_ready_callback: Callable[[dict[str, Any]], None] | None = None,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        session = self.create_session("素材 Wiki 生成")
        session_id = str(session.get("id") or "")
        if session_ready_callback:
            session_ready_callback(
                {
                    "sessionId": session_id,
                    "providerId": self.provider_id,
                    "modelId": self.model_id,
                }
            )
        response = self._send_prompt_with_session_polling(
            session_id,
            prompt_text,
            stream_callback=stream_callback,
            early_tool_command="wikibuild",
        )
        parsed = self._extract_wiki_blueprint_json(response)
        return {
            **parsed,
            "opencodeOutput": self._build_output_trace(session_id, response),
        }

    def generate_tender_parse_with_trace(
        self,
        prompt_text: str,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        session = self.create_session("S1 招标文件结构化解析")
        session_id = str(session.get("id") or "")
        response = self._send_prompt_with_session_polling(
            session_id,
            prompt_text,
            stream_callback=stream_callback,
        )
        parsed = self._extract_tender_parse_json(response)
        return {
            **parsed,
            "opencodeOutput": self._build_output_trace(session_id, response),
        }

    def review_business_commitments_with_trace(
        self,
        prompt_text: str,
    ) -> dict[str, Any]:
        session = self.create_session("商务标承诺语义复核")
        session_id = str(session.get("id") or "")
        response = self._send_prompt_with_session_polling(session_id, prompt_text)
        parsed = self._extract_commitment_review_json(response)
        return {
            **parsed,
            "opencodeOutput": self._build_output_trace(session_id, response),
        }

    def review_business_attachment_templates_with_trace(
        self,
        prompt_text: str,
    ) -> dict[str, Any]:
        session = self.create_session("商务标附件模板语义校验")
        session_id = str(session.get("id") or "")
        response = self._send_prompt_with_session_polling(session_id, prompt_text)
        parsed = self._extract_business_template_review_json(response)
        return {
            **parsed,
            "opencodeOutput": self._build_output_trace(session_id, response),
        }

    def list_session_messages(self, session_id: str) -> list[dict[str, Any]]:
        try:
            with httpx.Client(timeout=httpx.Timeout(5.0, connect=5.0)) as client:
                response = client.get(f"{self.base_url}/session/{session_id}/message")
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError):
            return []

        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    def _extract_outline_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = self._extract_json_response(
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

    def _extract_sections_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = self._extract_json_response(
            response,
            empty_message="futurecode 未返回正文内容。",
            repair_kind="sections",
        )
        if not isinstance(parsed, dict) or not isinstance(parsed.get("sections"), list):
            raise RuntimeError("futurecode 返回的正文 JSON 结构不正确。")
        return parsed

    def _extract_wiki_blueprint_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = self._extract_json_response(
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

    def _extract_assembly_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = self._extract_json_response(
            response,
            empty_message="futurecode 未返回正文拼装结果。",
            repair_kind="assembly",
        )
        if not isinstance(parsed, dict) or not isinstance(parsed.get("outputFile"), str):
            raise RuntimeError("futurecode 返回的正文拼装 JSON 结构不正确。")
        return parsed

    def _extract_business_format_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = self._extract_json_response(
            response,
            empty_message="futurecode 未返回商务标格式清洗结果。",
            repair_kind="business_format",
        )
        if not isinstance(parsed, dict) or not isinstance(parsed.get("outputFile"), str):
            raise RuntimeError("futurecode 返回的商务标格式清洗 JSON 结构不正确。")
        return parsed

    def _extract_gap_plan_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = self._extract_json_response(
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

    def _extract_tender_parse_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = self._extract_json_response(
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
        return parsed

    def _extract_commitment_review_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = self._extract_json_response(
            response,
            empty_message="futurecode 未返回承诺复核结果。",
            repair_kind="business_commitment_review",
        )
        if not isinstance(parsed, dict) or not isinstance(parsed.get("decisions"), list):
            raise RuntimeError("futurecode 返回的承诺复核 JSON 结构不正确。")
        return parsed

    def _extract_business_template_review_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = self._extract_json_response(
            response,
            empty_message="futurecode 未返回附件模板校验结果。",
            repair_kind="business_template_review",
        )
        if not isinstance(parsed, dict) or not isinstance(parsed.get("decisions"), list):
            raise RuntimeError("futurecode 返回的附件模板校验 JSON 结构不正确。")
        return parsed

    def _extract_table_fill_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = self._extract_json_response(
            response,
            empty_message="futurecode 未返回 AI 填写结果。",
            repair_kind="table_fill",
        )
        if not isinstance(parsed, dict) or not isinstance(parsed.get("outputFile"), str):
            raise RuntimeError("futurecode 返回的 AI 填写 JSON 结构不正确。")
        return parsed

    def _extract_json_response(
        self,
        response: dict[str, Any],
        empty_message: str,
        repair_kind: str,
    ) -> dict[str, Any]:
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
            return self._parse_json_payload(content)
        except RuntimeError as exc:
            if response.get("_earlyCompletion"):
                snippet = self._shorten_text(content, limit=420)
                raise RuntimeError(
                    f"futurecode 工具输出不是有效 JSON，已停止目录生成：{snippet}。"
                ) from exc
            if self._looks_like_tool_failure(content):
                snippet = self._shorten_text(content, limit=420)
                raise RuntimeError(f"futurecode 工具执行失败：{snippet}。") from exc
            try:
                repaired = self._repair_json_payload(content, repair_kind)
                return self._parse_json_payload(repaired)
            except RuntimeError as repair_error:
                snippet = self._shorten_text(content, limit=420)
                raise RuntimeError(
                    f"futurecode JSON 解析失败：{repair_error}；原始片段：{snippet}。"
                ) from repair_error

    def _send_prompt_with_session_polling(
        self,
        session_id: str,
        prompt_text: str,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
        early_tool_command: str = "",
    ) -> dict[str, Any]:
        if stream_callback is None and not early_tool_command:
            return self.send_prompt(session_id, prompt_text)

        response_holder: dict[str, Any] = {}
        error_holder: dict[str, Exception] = {}
        finished = threading.Event()

        def worker() -> None:
            try:
                response_holder["response"] = self.send_prompt(session_id, prompt_text)
            except Exception as exc:  # pragma: no cover - exercised via caller path
                error_holder["error"] = exc
            finally:
                finished.set()

        thread = threading.Thread(
            target=worker,
            daemon=True,
            name=f"opencode-message-{session_id}",
        )
        thread.start()

        last_signature: tuple[str, tuple[tuple[str, str], ...]] | None = None
        last_activity = time.monotonic()
        idle_timeout = max(120.0, min(float(settings.opencode_timeout_sec), 900.0))
        while not finished.wait(0.5):
            previous_signature = last_signature
            if stream_callback is not None:
                last_signature = self._emit_session_output_delta(
                    session_id,
                    stream_callback,
                    last_signature,
                )
            elif early_tool_command:
                snapshot = self._get_session_output_snapshot(session_id)
                signature = snapshot.get("signature")
                if signature is not None:
                    last_signature = signature
            if last_signature != previous_signature:
                last_activity = time.monotonic()
            elif time.monotonic() - last_activity > idle_timeout:
                raise RuntimeError(
                    f"futurecode idle timeout after {int(idle_timeout)} seconds without new output; "
                    f"check session {session_id} tool calls."
                )
            if early_tool_command:
                messages = self.list_session_messages(session_id)
                tool_output = self._find_completed_bash_tool_output(messages, early_tool_command)
                if tool_output:
                    snapshot = self._get_session_output_snapshot_from_messages(session_id, messages)
                    trace_parts = list(snapshot.get("parts") or [])
                    trace_parts.append(
                        {
                            "type": "text",
                            "text": (
                                f"{early_tool_command} 已完成，后端直接读取脚本产物，"
                                "不再等待 futurecode 继续读取大 JSON 文件。"
                            ),
                        }
                    )
                    early_response = self._tool_output_response(
                        session_id=session_id,
                        output=tool_output,
                        trace_parts=trace_parts,
                    )
                    early_response["_completionSource"] = early_tool_command
                    if stream_callback is not None:
                        stream_callback(
                            {
                                "status": "received",
                                "sessionId": session_id,
                                "providerId": self.provider_id,
                                "modelId": self.model_id,
                                "receivedAt": early_response["_traceReceivedAt"],
                                "parts": self._normalize_output_parts(trace_parts),
                                "earlyCompletion": True,
                                "completionSource": early_tool_command,
                            }
                        )
                    return early_response

        if stream_callback is not None:
            last_signature = self._emit_session_output_delta(
                session_id,
                stream_callback,
                last_signature,
            )
        thread.join()
        if error_holder.get("error"):
            raise error_holder["error"]
        return response_holder["response"]

    def _emit_session_output_delta(
        self,
        session_id: str,
        stream_callback: Callable[[dict[str, Any]], None],
        last_signature: tuple[str, tuple[tuple[str, str], ...]] | None,
    ) -> tuple[str, tuple[tuple[str, str], ...]] | None:
        snapshot = self._get_session_output_snapshot(session_id)
        signature = snapshot.get("signature")
        if signature is None or signature == last_signature:
            return last_signature

        stream_callback(
            {
                "status": snapshot["status"],
                "sessionId": session_id,
                "providerId": self.provider_id,
                "modelId": self.model_id,
                "receivedAt": snapshot["receivedAt"],
                "parts": snapshot["parts"],
            }
        )
        return signature

    def _get_session_output_snapshot(self, session_id: str) -> dict[str, Any]:
        return self._get_session_output_snapshot_from_messages(
            session_id,
            self.list_session_messages(session_id),
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

    @staticmethod
    def _find_completed_bash_tool_output(
        messages: list[dict[str, Any]],
        command_name: str,
    ) -> str:
        expected = str(command_name or "").strip()
        if not expected:
            return ""
        for message in reversed(messages):
            for part in reversed(message.get("parts") or []):
                if not isinstance(part, dict) or part.get("type") != "tool":
                    continue
                if str(part.get("tool") or "") != "bash":
                    continue
                state = part.get("state") if isinstance(part.get("state"), dict) else {}
                if state.get("status") != "completed":
                    continue
                raw_input = state.get("input") if isinstance(state.get("input"), dict) else {}
                command = str(raw_input.get("command") or "").strip()
                first_word = command.split(maxsplit=1)[0] if command else ""
                if first_word != expected:
                    continue
                exit_code = state.get("exit")
                if exit_code not in (None, 0):
                    continue
                output = str(state.get("output") or "").strip()
                if output and OpencodeClient._looks_like_json_object(output):
                    return output
                synthesized = OpencodeClient._synthesize_tool_response_from_manifest(command, expected)
                if synthesized:
                    return synthesized
        return ""

    @staticmethod
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
            business_outline_file = work_dir / "outline.json"
            if not business_outline_file.exists():
                return ""
            return json.dumps(
                {
                    "schema_version": "business_bid_outline.v1",
                    "businessOutlineFile": str(business_outline_file),
                    "outputFile": str(output_file),
                    "evidenceFile": str(evidence_file),
                    "summary": {"total_sections": 0},
                },
                ensure_ascii=False,
            )
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
    def _parse_json_payload(content: str) -> dict[str, Any]:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned)
            cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise RuntimeError("futurecode 返回内容里没有可解析的 JSON。")
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError as exc:  # pragma: no cover
                raise RuntimeError("futurecode 返回的 JSON 无法解析。") from exc

    @staticmethod
    def _looks_like_json_object(content: str) -> bool:
        text = str(content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text).strip()
        return text.startswith("{") and "}" in text

    @staticmethod
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
        return any(marker in text for marker in failure_markers) and not OpencodeClient._looks_like_json_object(text)

    @staticmethod
    def extract_text_response(response: dict[str, Any]) -> str:
        info = response.get("info") if isinstance(response.get("info"), dict) else {}
        if info.get("error"):
            return OpencodeClient._format_response_error(info["error"])
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
    def _format_response_error(error: Any) -> str:
        if not isinstance(error, dict):
            return str(error or "futurecode 调用失败。")
        name = str(error.get("name") or "futurecode 调用失败").strip()
        data = error.get("data") if isinstance(error.get("data"), dict) else {}
        message = str(data.get("message") or error.get("message") or "").strip()
        details = []
        provider_id = str(data.get("providerID") or data.get("providerId") or "").strip()
        model_id = str(data.get("modelID") or data.get("modelId") or "").strip()
        if provider_id:
            details.append(f"providerID={provider_id}")
        if model_id:
            details.append(f"modelID={model_id}")
        if message and message != name:
            name = f"{name}: {message}"
        if details:
            return f"{name} ({', '.join(details)})"
        return name or "futurecode 调用失败。"

    @staticmethod
    def is_model_not_found_error(error_text: Any) -> bool:
        text = str(error_text or "").lower()
        return "providermodelnotfound" in text or "modelnotfound" in text or "model not found" in text

    @staticmethod
    def _short_http_error(exc: Exception) -> str:
        detail = str(exc).replace("\n", " ").strip()
        return detail or "服务调用异常。"

    @staticmethod
    def _shorten_text(value: str, limit: int = 420) -> str:
        text = str(value).strip().replace("\n", " ")
        if len(text) <= limit:
            return text
        return f"{text[:limit - 3]}..."

    def _repair_json_payload(self, raw_content: str, repair_kind: str) -> str:
        if repair_kind == "outline":
            schema_hint = (
                '{"schema_version":"bid-toc-json-v1","summary":{"total_items":1,'
                '"annotation_counts":{"保留":1,"适配":0,"新增-招标要求":0,"新增-素材库建议":0,'
                '"删除建议":0,"素材内置标题":0}},"items":[{"order":1,"number":"第一章",'
                '"title":"一级标题","level":1,"annotation":"保留","source":"template","reason":""}],'
                '"outputFile":"/data/documents/PRJ-0001/technical-workspace/s2_toc_workdir/投标文件-总目录.json"}'
            )
        elif repair_kind == "wiki":
            schema_hint = (
                '{"summary":"一句简短总结","rootTitle":"技术标Wiki（自动生成）",'
                '"nodes":[{"title":"节点标题","markdownContent":"# 节点标题\\n\\n正文",'
                '"tags":["技术标","素材库"],"applicableTypes":["技术标"],"children":[]}]}'
            )
        elif repair_kind == "assembly":
            schema_hint = (
                '{"schema_version":"bid-tech-assembly-v1","outputFile":'
                '"/data/documents/PRJ-0001/technical-workspace/s7_assembly_workdir/投标文件-正文.docx",'
                '"assemblyReport":"/data/documents/PRJ-0001/technical-workspace/s7_assembly_workdir/assembly_report.md",'
                '"needsReview":"/data/documents/PRJ-0001/technical-workspace/s7_assembly_workdir/needs_review.md",'
                '"planFile":"/data/documents/PRJ-0001/technical-workspace/s7_assembly_workdir/assembly_plan.json",'
                '"summary":{"total":1,"byStatus":{"MATCHED":1},"usedPathCount":1}}'
            )
        elif repair_kind == "gap_plan":
            schema_hint = (
                '{"schema_version":"bid-tech-gap-plan-v1","outputFile":'
                '"/data/documents/PRJ-0001/technical-workspace/s4_gap_workdir/gap_plan.json",'
                '"summary":{"totalTocItems":1,"matchedCount":0,"missingCount":1,'
                '"resolvedCount":0,"ignoredCount":0,"structuralCount":0,'
                '"fillableTaskCount":1,"blockingCount":1},"itemCount":1}'
            )
        elif repair_kind == "tender_parse":
            schema_hint = (
                '{"schemaVersion":"bid-tender-structured-v1","outputFile":'
                '"/data/parsed/PRJ-0001/s1_structured_result.json",'
                '"items":[{"id":"REQ-0001","type":"项目基础信息","category":"project_basics",'
                '"title":"项目名称","keyEntity":"项目名称","keyValue":"示例项目",'
                '"sourceFile":"招标文件.docx","evidence":"项目名称：示例项目","evidenceLocation":"L1"}],'
                '"structured":{"projectDates":{"startDate":"2026-01-01","endDate":"2026-02-01"},'
                '"categories":[{"key":"project_basics","label":"项目基础信息","count":1,"items":[]}]}}'
            )
        elif repair_kind == "business_commitment_review":
            schema_hint = (
                '{"decisions":[{"id":"RAW-0001","action":"generate",'
                '"topicKey":"confidentiality","preferredTitle":"保密承诺书",'
                '"reason":"明确要求投标人单独提供保密承诺书。"}]}'
            )
        elif repair_kind == "business_template_review":
            schema_hint = (
                '{"decisions":[{"id":"APPX-0001","action":"accept|review|reject",'
                '"templateType":"bid_letter","quality":"complete|probably_incomplete|title_only",'
                '"reason":"一句简短原因"}]}'
            )
        elif repair_kind == "table_fill":
            schema_hint = (
                '{"schema_version":"bid-tech-table-fill-v1","outputFile":'
                '"/data/documents/PRJ-0001/technical-workspace/s4_gap_workdir/ai_fill/GAP-0001/AI填写.docx",'
                '"unfilledFields":[],"evidenceRefs":[{"type":"material","id":"RAW-0001"}]}'
            )
        elif repair_kind == "business_format":
            schema_hint = (
                '{"schema_version":"bid-business-format-clean-v1","inputFile":'
                '"/data/documents/PRJ-0001/business-workspace/s4_assembly_workdir/商务投标文件.docx",'
                '"outlineFile":"/data/documents/PRJ-0001/business-workspace/s4_assembly_workdir/business_format_outline.json",'
                '"outputFile":"/data/documents/PRJ-0001/business-workspace/s4_assembly_workdir/商务投标文件.formatted.docx",'
                '"reportFile":"/data/documents/PRJ-0001/business-workspace/s4_assembly_workdir/business_format_clean_report.md",'
                '"summary":{"outlineCount":1,"matchedHeadingCount":1,"unmatchedHeadingCount":0,'
                '"tocInserted":true,"tocPresent":true,"headerCleaned":true,"riskCount":0}}'
            )
        else:
            schema_hint = (
                '{"summary":"一句简短总结","sections":[{"nodeId":"OL-1","title":"章节标题",'
                '"generationMode":"generated","content":"正文","riskFlags":[]}]}'
            )
        repair_prompt = f"""
请把下面内容整理成严格 JSON。

要求：
1. 只输出 JSON，不要解释，不要 Markdown 代码块。
2. 保留原始语义，不要新增事实。
3. 输出结构必须满足这个模式：
{schema_hint}

原始内容：
{raw_content}
""".strip()
        session = self.create_session("JSON repair")
        response = self.send_prompt(str(session.get("id") or ""), repair_prompt)
        text_parts = [
            str(part.get("text") or "")
            for part in response.get("parts") or []
            if part.get("type") == "text"
        ]
        content = "\n".join(part for part in text_parts if part).strip()
        if not content:
            raise RuntimeError("futurecode 返回的 JSON 无法解析。")
        return content

    def _build_output_trace(self, session_id: str, response: dict[str, Any]) -> dict[str, Any]:
        info = response.get("info") or {}
        raw_time = info.get("time") or {}
        trace_parts = response.get("_traceParts")
        if not isinstance(trace_parts, list):
            trace_parts = response.get("parts") or []
        output = {
            "status": "received",
            "sessionId": session_id,
            "providerId": str(info.get("providerID") or self.provider_id),
            "modelId": str(info.get("modelID") or self.model_id),
            "receivedAt": str(response.get("_traceReceivedAt") or "")
            or self._coerce_timestamp(raw_time.get("completed") if isinstance(raw_time, dict) else raw_time),
            "parts": self._normalize_output_parts(trace_parts),
        }
        if response.get("_earlyCompletion"):
            output["earlyCompletion"] = True
            output["completionSource"] = str(response.get("_completionSource") or "tool")
        return output

    @staticmethod
    def _coerce_timestamp(value: Any) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            timestamp = float(value)
            if timestamp > 1_000_000_000_000:
                timestamp /= 1000.0
            return datetime.fromtimestamp(timestamp, UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _normalize_output_parts(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for part in parts:
            part_type = str(part.get("type") or "").strip()
            if part_type not in {"reasoning", "text", "step-start", "step-finish", "tool"}:
                continue
            text = str(part.get("text") or part.get("reasoning") or "").strip()
            if not text:
                if part_type == "step-start":
                    text = "futurecode 已开始处理目录生成请求。"
                elif part_type == "reasoning":
                    text = "futurecode 正在分析招标文件与投标模板。"
                elif part_type == "step-finish":
                    text = "futurecode 已完成一个处理步骤。"
                elif part_type == "tool":
                    tool_name = str(part.get("tool") or "工具").strip()
                    state = part.get("state") if isinstance(part.get("state"), dict) else {}
                    status = str(state.get("status") or "运行中").strip()
                    text = f"futurecode 正在调用 {tool_name}（{status}）。"
            normalized.append(
                {
                    "type": part_type,
                    "text": text,
                }
            )
        return normalized[-20:]
