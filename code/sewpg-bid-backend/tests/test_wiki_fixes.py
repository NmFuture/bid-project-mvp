"""Wiki 修复项的聚焦单测（只覆盖不依赖 DB/MinIO 的纯逻辑）。

对应审查修复：
- 2/7 自动生成来源标记（is_generated_wiki_doc / with_generated_wiki_tag）
- 4   applicableTypes 白名单（normalize_wiki_applicable_types）
- 5   附件 scope 与树可见性统一（wiki_root_visible_for_bid_type）
- 6   wiki_health 不再对 DB 形态恒定误报
- 10  refresh 摘要只剥离行首标题符号
"""

from __future__ import annotations

import re
from pathlib import Path

from app.services.bid_type import BUSINESS_BID_TYPE, GENERAL_BID_TYPE, TECHNICAL_BID_TYPE
from app.services.material_wiki_import import (
    GENERATED_WIKI_SOURCE_TAG,
    is_generated_wiki_doc,
    with_generated_wiki_tag,
)
from app.services.material_wiki_scope import (
    normalize_wiki_applicable_types,
    wiki_root_visible_for_bid_type,
)
from app.services.wiki_health import inspect_wiki_dir


# --- 2/7 自动生成来源标记 -------------------------------------------------

def test_with_generated_tag_adds_marker_and_dedupes():
    tags = with_generated_wiki_tag(["技术标"])
    assert GENERATED_WIKI_SOURCE_TAG in tags
    assert tags.count(GENERATED_WIKI_SOURCE_TAG) == 1
    # 已有标记不重复追加
    again = with_generated_wiki_tag(tags)
    assert again.count(GENERATED_WIKI_SOURCE_TAG) == 1
    # 原有 tag 保留
    assert "技术标" in again


def test_is_generated_wiki_doc_detection():
    assert is_generated_wiki_doc([GENERATED_WIKI_SOURCE_TAG, "技术标"]) is True
    # 手工节点默认无标记 → 视为非自动生成，refresh 时应保留
    assert is_generated_wiki_doc(["技术标"]) is False
    assert is_generated_wiki_doc([]) is False
    assert is_generated_wiki_doc(None) is False


# --- 4 applicableTypes 白名单 ---------------------------------------------

def test_normalize_wiki_applicable_types_valid():
    assert normalize_wiki_applicable_types([TECHNICAL_BID_TYPE]) == [TECHNICAL_BID_TYPE]
    assert normalize_wiki_applicable_types([GENERAL_BID_TYPE, BUSINESS_BID_TYPE]) == [
        GENERAL_BID_TYPE,
        BUSINESS_BID_TYPE,
    ]
    # 去重保序
    assert normalize_wiki_applicable_types([TECHNICAL_BID_TYPE, TECHNICAL_BID_TYPE]) == [
        TECHNICAL_BID_TYPE
    ]


def test_normalize_wiki_applicable_types_invalid_returns_none():
    # 空列表非法
    assert normalize_wiki_applicable_types([]) is None
    # 含非法值非法
    assert normalize_wiki_applicable_types(["乱写"]) is None
    assert normalize_wiki_applicable_types([TECHNICAL_BID_TYPE, "乱写"]) is None
    # 非列表非法
    assert normalize_wiki_applicable_types("技术标") is None
    assert normalize_wiki_applicable_types(None) is None


# --- 5 附件 scope 与树可见性统一 ------------------------------------------

def test_attachment_scope_uses_tree_visibility():
    # 同时含两条线的节点：对立标类存在 → 两条线都不可见（与树一致）
    both = [TECHNICAL_BID_TYPE, BUSINESS_BID_TYPE]
    assert wiki_root_visible_for_bid_type(title="子节点", bid_types=both, bid_type=TECHNICAL_BID_TYPE) is False
    assert wiki_root_visible_for_bid_type(title="子节点", bid_types=both, bid_type=BUSINESS_BID_TYPE) is False
    # 只含本标类 → 可见
    assert wiki_root_visible_for_bid_type(title="子节点", bid_types=[TECHNICAL_BID_TYPE], bid_type=TECHNICAL_BID_TYPE) is True
    # 根节点按 title 前缀判定
    assert wiki_root_visible_for_bid_type(title=f"{TECHNICAL_BID_TYPE}Wiki（自动生成）", bid_types=[], bid_type=TECHNICAL_BID_TYPE) is True
    assert wiki_root_visible_for_bid_type(title=f"{BUSINESS_BID_TYPE}Wiki（自动生成）", bid_types=[], bid_type=TECHNICAL_BID_TYPE) is False


# --- 6 wiki_health DB 形态不误报 ------------------------------------------

def test_wiki_health_skips_filesystem_check_when_dir_missing(tmp_path: Path):
    missing = tmp_path / "does_not_exist"
    health = inspect_wiki_dir(missing)
    # 不再恒定报 wiki_dir_not_found / no_wiki_cards
    assert "wiki_dir_not_found" not in health.warnings
    assert "no_wiki_cards" not in health.warnings
    assert health.warnings == ["db_backed_wiki_filesystem_check_skipped"]


# --- 10 refresh 摘要只剥离行首标题符号 ------------------------------------

def _summary(markdown: str) -> str:
    # 复刻 refresh_wiki_summary 里的摘要逻辑（避免 import DB 依赖模块）
    stripped = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", markdown)
    return re.sub(r"\s+", " ", stripped).strip()[:80] or "暂无摘要。"


def test_summary_strips_only_leading_heading_marks():
    md = "# 标题\n\n价格约 3#5 元，编号 A#B。"
    summary = _summary(md)
    # 行首标题符号被剥离
    assert not summary.startswith("#")
    assert "标题" in summary
    # 正文中的 # 保留，不被误删
    assert "3#5" in summary
    assert "A#B" in summary
