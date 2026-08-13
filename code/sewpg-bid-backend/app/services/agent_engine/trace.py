"""输出轨迹留痕公共能力（改造方案 §5，引擎无关，三引擎复用）。

函数体自 `app/services/opencode_client.py`（现 `opencode_engine.py`）纯移动，未改逻辑。
`_build_output_trace` 读取引擎实例的 provider/model：第一个参数 `self`
即引擎实例（`OpencodeEngine` 以类属性引用本函数，保持原访问形态）。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


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


def _coerce_timestamp(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 1_000_000_000_000:
            timestamp /= 1000.0
        return datetime.fromtimestamp(timestamp, UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
