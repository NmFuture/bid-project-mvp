from __future__ import annotations

from typing import Any

from app.services.bid_type import BUSINESS_BID_TYPE, GENERAL_BID_TYPE, TECHNICAL_BID_TYPE

WIKI_BID_TYPES = {TECHNICAL_BID_TYPE, BUSINESS_BID_TYPE}
DEFAULT_WIKI_APPLICABLE_TYPE = GENERAL_BID_TYPE
DEFAULT_PLATFORM_WIKI_ROOT_TITLE = "平台级Wiki（自动生成）"
GENERATED_WIKI_CHILD_TITLES = ("01-素材总表", "02-章节映射表", "03-素材卡片", "04-待填写清单", "05-使用规则")
WIKI_TAG_OPTIONS = [TECHNICAL_BID_TYPE, BUSINESS_BID_TYPE, "通用素材", "客户素材", "项目素材", "日志"]
WIKI_APPLICABLE_TYPE_OPTIONS = [TECHNICAL_BID_TYPE, BUSINESS_BID_TYPE]


def normalize_wiki_bid_type(value: Any) -> str:
    text = str(value or "").strip()
    return text if text in WIKI_BID_TYPES else ""


def wiki_node_bid_types(
    *,
    bid_type: str,
    parent_bid_types: list[str] | tuple[str, ...] | set[str] | None = None,
) -> list[str]:
    inherited = [str(item) for item in (parent_bid_types or []) if str(item or "").strip()]
    if inherited:
        return inherited
    normalized_bid_type = normalize_wiki_bid_type(bid_type)
    return [normalized_bid_type] if normalized_bid_type else [DEFAULT_WIKI_APPLICABLE_TYPE]


def opposite_wiki_bid_type(bid_type: str) -> str:
    return BUSINESS_BID_TYPE if bid_type == TECHNICAL_BID_TYPE else TECHNICAL_BID_TYPE


def wiki_root_bid_type(root_title: str) -> str:
    title = str(root_title or "").strip()
    if title.startswith(BUSINESS_BID_TYPE):
        return BUSINESS_BID_TYPE
    return TECHNICAL_BID_TYPE


def wiki_root_visible_for_bid_type(
    *,
    title: str,
    bid_types: list[str] | tuple[str, ...] | set[str] | None,
    bid_type: str,
) -> bool:
    normalized_bid_type = normalize_wiki_bid_type(bid_type)
    if not normalized_bid_type:
        return True

    normalized_title = str(title or "")
    if normalized_title.startswith(f"{normalized_bid_type}Wiki"):
        return True

    opposite_bid_type = opposite_wiki_bid_type(normalized_bid_type)
    if normalized_title.startswith(f"{opposite_bid_type}Wiki") or normalized_title == DEFAULT_PLATFORM_WIKI_ROOT_TITLE:
        return False

    type_set = {str(item) for item in (bid_types or [])}
    return normalized_bid_type in type_set and opposite_bid_type not in type_set
