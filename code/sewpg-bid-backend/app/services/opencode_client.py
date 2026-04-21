from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from typing import Any, Callable

import httpx

from app.core.config import settings


class OpencodeClient:
    def __init__(self) -> None:
        self.base_url = settings.opencode_base_url.rstrip("/")
        self.provider_id = settings.opencode_provider_id
        self.model_id = settings.opencode_model_id
        self.timeout = httpx.Timeout(settings.opencode_timeout_sec, connect=10.0)

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
        session = self.create_session("S7 初稿生成")
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
        if not isinstance(parsed, dict) or not isinstance(parsed.get("nodes"), list):
            raise RuntimeError("futurecode 返回的目录 JSON 结构不正确。")
        return parsed

    def _extract_sections_json(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed = self._extract_json_response(
            response,
            empty_message="futurecode 未返回初稿内容。",
            repair_kind="sections",
        )
        if not isinstance(parsed, dict) or not isinstance(parsed.get("sections"), list):
            raise RuntimeError("futurecode 返回的初稿 JSON 结构不正确。")
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
    ) -> dict[str, Any]:
        if stream_callback is None:
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
        while not finished.wait(0.5):
            last_signature = self._emit_session_output_delta(
                session_id,
                stream_callback,
                last_signature,
            )

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
        assistant_message: dict[str, Any] | None = None
        fallback_assistant: dict[str, Any] | None = None
        messages = self.list_session_messages(session_id)
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
        schema_hint = (
            '{"summary":"一句简短总结","nodes":[{"id":"OL-1","title":"一级标题","children":[]}]}'
            if repair_kind == "outline"
            else '{"summary":"一句简短总结","sections":[{"nodeId":"OL-1","title":"章节标题","generationMode":"generated","content":"正文","riskFlags":[]}]}'
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
        return {
            "status": "received",
            "sessionId": session_id,
            "providerId": str(info.get("providerID") or self.provider_id),
            "modelId": str(info.get("modelID") or self.model_id),
            "receivedAt": self._coerce_timestamp(
                raw_time.get("completed") if isinstance(raw_time, dict) else raw_time
            ),
            "parts": self._normalize_output_parts(response.get("parts") or []),
        }

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
            if part_type not in {"reasoning", "text", "step-start", "step-finish"}:
                continue
            text = str(part.get("text") or part.get("reasoning") or "").strip()
            normalized.append(
                {
                    "type": part_type,
                    "text": text,
                }
            )
        return normalized[-20:]
