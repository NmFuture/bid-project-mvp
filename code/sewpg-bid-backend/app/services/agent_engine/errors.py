"""错误归一化公共能力（改造方案 §5，引擎无关，三引擎复用）。

`_format_response_error` / `is_model_not_found_error` / `_short_http_error`
函数体自 `app/services/opencode_client.py`（现 `opencode_engine.py`）纯移动，未改逻辑。

B2（engine-04）新增可恢复错误分类（对齐 create_session 既有
`_SESSION_CREATE_RETRYABLE_STATUS_CODES` 白名单语义）与两类显式异常：
- `PromptDeliveryUncertainError`：prompt 送达状态不确定（可能已送达但响应丢失），
  自动重发会重复执行，禁止自动重试，显式报错并保留上下文。
- `PollReconnectExhaustedError`：轮询断线重连预算耗尽，显式报「断线」，
  不与「模型 stall（idle 超时）」混同。
两者都是 RuntimeError 子类，调用方既有 `except RuntimeError` 语义不变。
"""
from __future__ import annotations

from typing import Any

import httpx

# 与 create_session 既有白名单同源：网关/服务端临时不可用。
RETRYABLE_HTTP_STATUS_CODES = frozenset({429, 502, 503, 504})


class PromptDeliveryUncertainError(RuntimeError):
    """prompt 送达状态不确定（读超时/5xx/连接中途断开），不可自动重发。

    重发会让 opencode 对同一会话重复执行同一 prompt；此类错误必须由上层
    （会话级重试或人工）显式决策。
    """


class PollReconnectExhaustedError(RuntimeError):
    """轮询 GET messages 断线重连预算耗尽：显式报断线，非模型 stall。"""


def is_pre_delivery_error(exc: Exception) -> bool:
    """连接未建立（请求字节未写出）→ prompt 确认未送达，重发幂等安全。

    `httpx.ConnectError`：TCP 连接失败；`httpx.ConnectTimeout`：连接阶段超时
    （注意它是 TimeoutException 子类而非 ConnectError 子类，需并列判断）。
    """
    return isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout))


def is_recoverable_poll_error(exc: Exception) -> bool:
    """轮询 GET messages 失败是否可重连续轮询（GET 幂等，重试无重复执行风险）。

    可恢复：连接断开/连接超时/读超时/对端无响应断连、429/502/503/504、
    非 JSON 响应（多为网关错误页）。其余（4xx/500 等确定性错误）不可恢复。
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_HTTP_STATUS_CODES
    if isinstance(
        exc,
        (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError),
    ):
        return True
    return isinstance(exc, ValueError)


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
