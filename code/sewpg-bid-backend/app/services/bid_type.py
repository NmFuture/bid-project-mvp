from __future__ import annotations

from typing import Any


TECHNICAL_BID_TYPE = "技术标"
BUSINESS_BID_TYPE = "商务标"
GENERAL_BID_TYPE = "通用"
BID_TYPES = {TECHNICAL_BID_TYPE, BUSINESS_BID_TYPE, GENERAL_BID_TYPE}


def normalize_bid_type(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    if text in BID_TYPES:
        return text
    if "商务" in text:
        return BUSINESS_BID_TYPE
    if "技术" in text:
        return TECHNICAL_BID_TYPE
    return default


def require_bid_type(
    value: Any,
    *,
    allow_general: bool = False,
    error_message: str = "标类必须是技术标或商务标。",
) -> str:
    normalized = normalize_bid_type(value, "")
    allowed = BID_TYPES if allow_general else {TECHNICAL_BID_TYPE, BUSINESS_BID_TYPE}
    if normalized in allowed:
        return normalized
    raise ValueError(error_message)


def is_business_bid_type(value: Any) -> bool:
    return normalize_bid_type(value, "") == BUSINESS_BID_TYPE


def is_technical_bid_type(value: Any) -> bool:
    return normalize_bid_type(value, "") == TECHNICAL_BID_TYPE
