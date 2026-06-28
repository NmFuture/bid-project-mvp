from __future__ import annotations

import re
from typing import Any

from app.services.material_wiki_scope import (
    DEFAULT_PLATFORM_WIKI_ROOT_TITLE,
    DEFAULT_WIKI_APPLICABLE_TYPE,
    wiki_root_bid_type,
)


AUTO_WIKI_DOC_SUMMARY = "自动生成的 Wiki 初稿节点。"
DEFAULT_WIKI_NODE_TITLE = "未命名节点"
VALID_WIKI_IMPORT_MODES = {"create", "update", "replace", "refresh"}


def safe_wiki_segment(value: str, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback


def normalize_wiki_import_mode(mode: str) -> str:
    normalized = str(mode or "").strip()
    return normalized if normalized in VALID_WIKI_IMPORT_MODES else "create"


def normalize_generated_wiki_root_title(root_title: str) -> str:
    return safe_wiki_segment(root_title, DEFAULT_PLATFORM_WIKI_ROOT_TITLE)


def build_generated_wiki_root_spec(
    *,
    root_title: str,
    root_markdown_content: str = "",
    nodes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_title = normalize_generated_wiki_root_title(root_title)
    root_bid_type = wiki_root_bid_type(normalized_title)
    return {
        "title": normalized_title,
        "markdownContent": root_markdown_content
        or f"# {normalized_title}\n\n这是系统自动生成的分标类 Wiki 根节点。",
        "tags": [root_bid_type, "素材库"],
        "applicableTypes": [root_bid_type],
        "children": list(nodes or []),
    }


def wiki_import_node_title(spec: dict[str, Any]) -> str:
    return safe_wiki_segment(str(spec.get("title") or DEFAULT_WIKI_NODE_TITLE), DEFAULT_WIKI_NODE_TITLE)


def wiki_import_node_markdown(spec: dict[str, Any], title: str, fallback: str = "") -> str:
    return str(spec.get("markdownContent") or fallback or f"# {title}\n")


def wiki_import_node_tags(spec: dict[str, Any], fallback: list[str] | None = None) -> list[str]:
    return list(spec.get("tags") or fallback or [])


def wiki_import_node_bid_types(spec: dict[str, Any], fallback: list[str] | None = None) -> list[str]:
    return list(spec.get("applicableTypes") or fallback or [DEFAULT_WIKI_APPLICABLE_TYPE])


def generated_wiki_import_message(root_title: str, outcome: str) -> str:
    root_bid_type = wiki_root_bid_type(root_title)
    messages = {
        "replaced": f"{root_bid_type} Wiki 已重新生成并覆盖。",
        "refreshed": f"{root_bid_type} Wiki 已按索引增量刷新。",
        "updated": f"{root_bid_type} Wiki 已更新，并已清理重复根节点。",
        "kept": f"{root_bid_type} Wiki 已存在，已保留现有版本并清理重复根节点。",
        "created": f"{root_bid_type} Wiki 创建成功。",
    }
    return messages.get(outcome, messages["created"])
