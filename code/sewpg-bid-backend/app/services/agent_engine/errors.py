"""错误归一化公共能力（改造方案 §5，引擎无关，三引擎复用）。

函数体自 `app/services/opencode_client.py`（现 `opencode_engine.py`）纯移动，未改逻辑。
"""
from __future__ import annotations

from typing import Any


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


def is_model_not_found_error(error_text: Any) -> bool:
    text = str(error_text or "").lower()
    return "providermodelnotfound" in text or "modelnotfound" in text or "model not found" in text


def _short_http_error(exc: Exception) -> str:
    detail = str(exc).replace("\n", " ").strip()
    return detail or "服务调用异常。"
