#!/usr/bin/env python3
"""
构建装配计划：toc.json × wiki 卡片 × project_params → assembly_plan.json。

匹配规则：
  1. 附表 A-I 段（level=1 且 title=='附表' 之后的条目）→ status=OUT_OF_SCOPE
  2. 前言段（is_preface=True）→ 查 skeleton_section=='前言'
  3. 附字头条目（is_appendix=True）→ 按 title 字符串匹配定制卡片 name
  4. tag=新增 → NEEDS_REVIEW, paths=[]（生成占位）
  5. tag=适配 或 normal：
     * chapter_no_flat 精确匹配卡片 skeleton_section
     * 多份：通用在前，定制在后
     * tag=适配 → 标 field_replace=True

输出每条：
  {
    toc_idx, level, chapter_no_flat, title, tag,
    is_preface, is_appendix, status,
    paths: [...],             # 素材相对路径（相对素材库根）
    shift: int,
    attach_mode: str,
    field_replace: bool,
    notes: str,
  }

用法：
    python3 build_assembly.py \\
        --toc /tmp/toc.json \\
        --wiki /Users/wlb/Downloads/技术标/素材库/wiki \\
        --out /tmp/assembly_plan.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

import yaml


# ---------- 卡片加载 ----------

@dataclass
class Card:
    name: str
    path: str          # 相对素材库根
    scope: str         # 通用 / 定制
    category: str
    skeleton_section: str
    skeleton_level: str = ""
    material_level_range: str = ""
    heading_count: int = 0
    shift: int = 0
    attach_mode: str = "normal"
    deprecated: bool = False
    card_file: str = ""

    @property
    def scope_rank(self) -> int:
        # 通用在前=0, 定制在后=1
        return 0 if self.scope == "通用" else 1


def load_cards(wiki_root: Path) -> list[Card]:
    cards: list[Card] = []
    for md in wiki_root.glob("卡片/**/*.md"):
        text = md.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        if not m:
            continue
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            continue
        if fm.get("deprecated"):
            continue
        c = Card(
            name=str(fm.get("name", md.stem)),
            path=str(fm.get("path", "")),
            scope=str(fm.get("scope", "通用")),
            category=str(fm.get("category", "")),
            skeleton_section=str(fm.get("skeleton_section", "")),
            skeleton_level=str(fm.get("skeleton_level", "")),
            material_level_range=str(fm.get("material_level_range", "")),
            heading_count=int(fm.get("heading_count", 0) or 0),
            shift=int(fm.get("shift", 0) or 0),
            attach_mode=str(fm.get("attach_mode", "normal") or "normal"),
            deprecated=bool(fm.get("deprecated", False)),
            card_file=str(md),
        )
        cards.append(c)
    return cards


def index_cards(cards: list[Card]) -> dict[str, list[Card]]:
    """按 skeleton_section 分组。"""
    idx: dict[str, list[Card]] = {}
    for c in cards:
        idx.setdefault(c.skeleton_section, []).append(c)
    # 同 section 内排序：通用在前、定制在后
    for sec in idx:
        idx[sec].sort(key=lambda c: (c.scope_rank, c.name))
    return idx


# ---------- 状态 ----------

# -------- 通用↔定制规则（从 wiki/rules.md 派生） --------
# (generic_card_name, custom_card_name) → mode
#   "override" = 定制覆盖通用（只留定制）
#   "stack"    = 叠加（两份都留，定制在前）
#   "append"   = 通用作正文，定制作附件（两份都留，通用在前）
GENERIC_CUSTOM_RULES = {
    ("技术标-项目技术承诺函", "项目技术承诺函"): "override",
    ("技术标-投标机型业绩情况", "投标机型业绩情况"): "stack",
    ("技术标-风资源评估与机位排布方案", "风资源评估与机位排布方案"): "override",
    ("技术标-齿轮箱专题", "齿轮箱场址校核报告"): "append",
    ("技术标-主轴专题", "主轴强度复核报告（北区）"): "append",
    ("技术标-主轴专题", "主轴强度复核报告（南区）"): "append",
    ("技术标-主轴承专题", "主轴轴承场址校核报告"): "append",
    ("技术标-叶片专题", "叶片场址校核报告"): "append",
    ("技术标-偏航系统专题", "偏航驱动与制动能力校核报告"): "append",
    ("技术标-变桨系统专题", "变桨轴承场址校核报告"): "append",
}

STATUS_COVER = "COVER"                # 封面（L0，在所有 toc 条目之前）
STATUS_MATCHED = "MATCHED"            # 正常命中
STATUS_ADAPTED = "ADAPTED"            # 命中 + 适配（field_replace）
STATUS_NEEDS_REVIEW = "NEEDS_REVIEW"  # 新增，无素材，占位
STATUS_UNMATCHED = "UNMATCHED"        # normal 但找不到
STATUS_STRUCTURAL = "STRUCTURAL"      # 伞形章节，仅结构空标题（如"第一章"/"5.8"）
STATUS_OUT_OF_SCOPE = "OUT_OF_SCOPE"  # 附表 A-I 区


# ---------- 匹配 ----------

def find_attach_zone_start(toc: list[dict]) -> int:
    """定位附表 A-I 区起始 idx；没找到返回 len(toc)（即不存在附表区）。"""
    for i, e in enumerate(toc):
        if e.get("level") == 1 and e.get("title", "").strip() == "附表":
            return i
    return len(toc)


def match_preface(card_idx: dict[str, list[Card]], entry: dict) -> dict:
    cards = card_idx.get("前言", [])
    if not cards:
        return {"status": STATUS_UNMATCHED, "paths": [], "shifts": [], "attach_modes": [], "note": "前言卡片缺失"}
    return {
        "status": STATUS_MATCHED,
        "paths": [c.path for c in cards],
        "shifts": [c.shift for c in cards],
        "attach_modes": [c.attach_mode for c in cards],
        "note": "",
    }


def match_appendix(cards_by_name: dict[str, Card], entry: dict) -> dict:
    """'附 xxx 校核报告' → 按 title 模糊匹配定制卡片 name。"""
    title = entry.get("title", "")
    matched: list[Card] = []
    for name, card in cards_by_name.items():
        if card.scope != "定制":
            continue
        # 卡片 name 或 title 反向包含
        if name in title or title.replace("（", "(").replace("）", ")") in name:
            matched.append(card)
        else:
            # 关键词匹配（去掉 "报告" "校核" 之类后缀）
            core = re.sub(r"(校核报告|复核报告|报告|校核|复核)$", "", name)
            if core and core in title:
                matched.append(card)
    if not matched:
        return {"status": STATUS_UNMATCHED, "paths": [], "shifts": [], "attach_modes": [], "note": f"附字头未匹配到定制卡片: {title}"}
    return {
        "status": STATUS_MATCHED,
        "paths": [c.path for c in matched],
        "shifts": [c.shift for c in matched],
        "attach_modes": [c.attach_mode for c in matched],
        "note": "",
    }


def _card_core_name(name: str) -> str:
    """从卡片 name 提取核心关键词串：去'技术标-'前缀、去'（如有）'后缀、去括号修饰。"""
    s = name
    if s.startswith("技术标-"):
        s = s[len("技术标-"):]
    s = re.sub(r"[（(][^）)]*[）)]\s*$", "", s)  # 去末尾括号修饰
    return s.strip()


def _score_match(toc_title: str, card_name: str) -> int:
    """按 card 核心名的 2-4 字子串在 toc_title 出现计分；title 完整含 card core 额外加权。"""
    if not toc_title or not card_name:
        return 0
    core = _card_core_name(card_name)
    if not core:
        return 0
    score = 0
    if core in toc_title:
        score += 100  # 完整包含加重
    # 子串滑窗
    for n in (4, 3, 2):
        for i in range(len(core) - n + 1):
            if core[i:i + n] in toc_title:
                score += n
    return score


def _is_conditional_card(card: "Card") -> bool:
    """素材名含'如有'字样的默认需要条件触发。"""
    return "如有" in card.name


def _apply_generic_custom_rules(cards: list["Card"]) -> list["Card"]:
    """按 GENERIC_CUSTOM_RULES 裁剪 cards 列表：
    - 覆盖：只保留定制
    - 叠加：两份都留，定制在前
    - 附加：两份都留，通用在前
    """
    generic = [c for c in cards if c.scope == "通用"]
    custom = [c for c in cards if c.scope == "定制"]
    if not (generic and custom):
        return cards  # 只有一种 scope，不适用规则

    new_list: list[Card] = []
    # 对每个定制卡片，找是否和某个通用卡片有规则
    matched_pairs: list[tuple[Card, Card, str]] = []  # (G, C, mode)
    untreated_generic = list(generic)
    untreated_custom = list(custom)
    for g in generic:
        for c in custom:
            mode = GENERIC_CUSTOM_RULES.get((g.name, c.name))
            if mode:
                matched_pairs.append((g, c, mode))
                if g in untreated_generic:
                    untreated_generic.remove(g)
                if c in untreated_custom:
                    untreated_custom.remove(c)

    # 处理匹配对
    for g, c, mode in matched_pairs:
        if mode == "override":
            new_list.append(c)  # 只要定制
        elif mode == "stack":
            new_list.extend([c, g])  # 定制在前
        elif mode == "append":
            new_list.extend([g, c])  # 通用在前
        else:
            new_list.extend([g, c])
    # 未匹配规则的卡片默认保留（通用在前，定制在后）
    new_list.extend(untreated_generic)
    new_list.extend(untreated_custom)
    # 去重（保顺序）
    seen_names = set()
    dedup = []
    for c in new_list:
        if c.name in seen_names:
            continue
        seen_names.add(c.name)
        dedup.append(c)
    return dedup


def _pick_cards_for_entry(cards: list["Card"], toc_title: str) -> list["Card"]:
    """从候选卡片里按 toc_title 语义筛选 + 规则应用。

    策略：
    1. 若卡片数 <= 1，直接返回
    2. 若有多张，先按 title 匹配打分：
       - 完全匹配（score>=100）的卡片优先
       - 完全无匹配的"（如有）"卡片剔除（条件触发未验证）
       - 保留打分 >0 的
       - 若最高分显著高于其他（>2×），只保留最高分对应的 scope 集
    3. 对剩余集合应用通用↔定制规则
    """
    if len(cards) <= 1:
        # 单张也要过"如有"过滤
        if cards and _is_conditional_card(cards[0]):
            if _score_match(toc_title, cards[0].name) < 100:
                return []
        return cards

    scored = [(c, _score_match(toc_title, c.name)) for c in cards]
    # 剔除"如有"且分数低
    scored = [
        (c, s) for c, s in scored
        if not (_is_conditional_card(c) and s < 100)
    ]
    if not scored:
        return []

    # 若存在完全匹配（>=100），只保留这些
    full_matches = [c for c, s in scored if s >= 100]
    if full_matches:
        picked = full_matches
    else:
        # 按分数截断：取最高分或与最高分相近的（差 <= 最高分 /3）
        max_s = max(s for _, s in scored)
        if max_s <= 0:
            return []
        picked = [c for c, s in scored if s >= max(max_s * 2 // 3, 2)]

    # 应用通用↔定制规则
    picked = _apply_generic_custom_rules(picked)
    return picked


def match_normal(card_idx: dict[str, list[Card]], entry: dict, tag: str) -> dict:
    sec = entry.get("chapter_no_flat") or ""
    cards_all = card_idx.get(sec, [])
    cards = _pick_cards_for_entry(cards_all, entry.get("title", ""))
    if cards:
        status = STATUS_ADAPTED if tag == "适配" else STATUS_MATCHED
        return {
            "status": status,
            "paths": [c.path for c in cards],
            "shifts": [c.shift for c in cards],
            "attach_modes": [c.attach_mode for c in cards],
            "note": "",
        }
    return {
        "status": STATUS_UNMATCHED,
        "paths": [],
        "shifts": [],
        "attach_modes": [],
        "note": f"skeleton_section={sec!r} 无卡片或无匹配",
    }


def is_umbrella(entry: dict, all_entries: list[dict]) -> bool:
    """判断当前 entry 是否伞形章节：有更深层的直接子节。

    条件：level=1（章级）总是伞形；
    其它：存在某 entry2 的 chapter_no_flat 以当前 chapter_no_flat+'.' 为前缀。
    """
    if entry["level"] == 1 and (entry.get("chapter_no", "").startswith("第") or not entry.get("chapter_no_flat")):
        # 第X章 级头 或 无编号的章级分段（如 "附表"）
        return True
    cur = entry.get("chapter_no_flat") or ""
    if not cur:
        return False
    prefix = cur + "."
    for e in all_entries:
        other = e.get("chapter_no_flat") or ""
        if other.startswith(prefix):
            return True
    return False


def try_prefix_fallback(
    card_idx: dict[str, list[Card]],
    entry: dict,
    tag: str,
) -> Optional[dict]:
    """UNMATCHED 时，尝试用前缀回退：chapter_no_flat='5.10.1' → 试 '5.10'。

    回退时按 toc title 在父节的所有卡片里做语义匹配，只取匹配到的那张。
    """
    cur = entry.get("chapter_no_flat") or ""
    if "." not in cur:
        return None
    parts = cur.split(".")
    title = entry.get("title", "")
    entry_depth = len(parts)
    for cut in range(len(parts) - 1, 0, -1):
        prefix = ".".join(parts[:cut])
        cards_all = card_idx.get(prefix, [])
        if not cards_all:
            continue
        # 防护：卡片自身是整章/整节素材（skeleton_section 深度 < entry 深度）时不 fallback
        # 例："skeleton_section=3" 代表整个第三章素材，不应被挂到 3.8 子节下
        cards_all = [
            c for c in cards_all
            if len((c.skeleton_section or "").split(".")) >= entry_depth
        ]
        if not cards_all:
            continue
        # 按 title 精准匹配：要求 score>0，且优先 >=100
        scored = [(c, _score_match(title, c.name)) for c in cards_all]
        scored = [(c, s) for c, s in scored if s > 0]
        if not scored:
            continue
        full = [c for c, s in scored if s >= 100]
        picked = full if full else [c for c, s in scored if s == max(s for _, s in scored)]
        picked = _apply_generic_custom_rules(picked)
        if not picked:
            continue
        status = STATUS_ADAPTED if tag == "适配" else STATUS_MATCHED
        return {
            "status": status,
            "paths": [c.path for c in picked],
            "shifts": [c.shift for c in picked],
            "attach_modes": [c.attach_mode for c in picked],
            "note": f"前缀回退：{cur} → {prefix}",
        }
    return None


def _split_keywords(text: str) -> list[str]:
    """从标题抽关键词用于卡片 name 匹配。简单取 2-6 字窗口。"""
    # 去掉常见词
    text = re.sub(r"专题$|方案$|系统$|（如有）$", "", text)
    if len(text) <= 6:
        return [text] if text else []
    # 尝试拆关键词：一般 2-4 字核心名词
    # 简单做法：切每个 2-4 字子串
    keywords = set()
    for n in (4, 3, 2):
        for i in range(len(text) - n + 1):
            keywords.add(text[i:i + n])
    return list(keywords)


# ---------- 主流程 ----------

def build_plan(
    toc: list[dict],
    cards: list[Card],
    project_params: dict,
) -> list[dict]:
    card_idx = index_cards(cards)
    cards_by_name = {c.name: c for c in cards}
    attach_start = find_attach_zone_start(toc)

    plan: list[dict] = []

    # Step 0: 先插入封面（若 wiki 有 skeleton_section="封面" 的卡片）
    cover_cards = card_idx.get("封面", [])
    if cover_cards:
        plan.append({
            "toc_idx": -1,
            "level": 0,
            "chapter_no_flat": "",
            "chapter_no": "",
            "title": "封面",
            "raw_text": "封面",
            "tag": "normal",
            "is_preface": False,
            "is_appendix": False,
            "paths": [c.path for c in cover_cards],
            "shifts": [c.shift for c in cover_cards],
            "attach_modes": [c.attach_mode for c in cover_cards],
            "field_replace": True,  # 封面必然需要占位符替换
            "status": STATUS_COVER,
            "note": "封面位于文档最前，attach_mode=cover",
        })

    for entry in toc:
        idx = entry["idx"]
        base = {
            "toc_idx": idx,
            "level": entry["level"],
            "chapter_no_flat": entry.get("chapter_no_flat", ""),
            "chapter_no": entry.get("chapter_no", ""),
            "title": entry["title"],
            "raw_text": entry["raw_text"],
            "tag": entry["tag"],
            "is_preface": entry["is_preface"],
            "is_appendix": entry["is_appendix"],
            "paths": [],
            "shifts": [],
            "attach_modes": [],
            "field_replace": entry["tag"] == "适配",
            "status": STATUS_UNMATCHED,
            "note": "",
        }

        # 附表 A-I 区
        if idx >= attach_start:
            base["status"] = STATUS_OUT_OF_SCOPE
            base["note"] = "附表 A-I 区，本 skill 不处理"
            plan.append(base)
            continue

        # 新增：无素材，占位
        if entry["tag"] == "新增":
            base["status"] = STATUS_NEEDS_REVIEW
            base["note"] = "招标/模板新增章节，需人工补素材"
            plan.append(base)
            continue

        # 前言
        if entry["is_preface"]:
            r = match_preface(card_idx, entry)
            base.update(r)
            plan.append(base)
            continue

        # 附
        if entry["is_appendix"]:
            r = match_appendix(cards_by_name, entry)
            base.update(r)
            plan.append(base)
            continue

        # normal/适配
        r = match_normal(card_idx, entry, entry["tag"])
        # 若 UNMATCHED，先尝试前缀回退；再判断是否伞形章节
        if r["status"] == STATUS_UNMATCHED:
            fallback = try_prefix_fallback(card_idx, entry, entry["tag"])
            if fallback:
                r = fallback
            elif is_umbrella(entry, toc):
                r = {
                    "status": STATUS_STRUCTURAL,
                    "paths": [],
                    "shifts": [],
                    "attach_modes": [],
                    "note": "伞形章节，仅写标题占位",
                }
        base.update(r)
        plan.append(base)

    return plan


# ---------- Appendix 语义重排（修目录 docx 把附字头错放的位置） ----------

_APPENDIX_SUFFIX = re.compile(r"(场址)?(校核|复核)报告(（[^）]*）)?\s*$")


def _appendix_core_tokens(title: str) -> str:
    """'偏航驱动与制动能力校核报告' → '偏航驱动与制动能力'。"""
    if not title:
        return ""
    return _APPENDIX_SUFFIX.sub("", title).strip()


def _semantic_score(app_core: str, normal_title: str) -> int:
    """附字头核心词 vs normal 条目 title 的重合度评分。"""
    if not app_core or not normal_title:
        return 0
    score = 0
    # 完整包含最可信
    if app_core in normal_title or normal_title in app_core:
        score += 100
    # 前缀匹配（附件核心词多以"部件/系统名"打头，如 偏航驱动... / 齿轮箱场址... / 主轴轴承...）
    for n in (4, 3, 2):
        if len(app_core) >= n and app_core[:n] in normal_title:
            score += 30 + n  # 前缀优先级高于中段
            break
    # n-gram overlap
    for n in (4, 3, 2):
        for i in range(len(app_core) - n + 1):
            if app_core[i:i + n] in normal_title:
                score += n
    return score


def rearrange_appendices(plan: list[dict]) -> list[dict]:
    """目录 docx 里常把附字头错放到别的 normal 条目后。本函数按 title 语义匹配
    把 appendix 重排到最佳 normal 父之后。未匹配到更好 parent 的保持原位置。

    重排只动 is_appendix=True 且 status in (MATCHED/ADAPTED) 的条目。
    """
    # 候选 parent：level >= 2 的 non-appendix 条目（章级以下，有 chapter_no_flat）
    candidates = [p for p in plan if not p.get("is_appendix") and p.get("chapter_no_flat")]
    if not candidates:
        return plan

    non_app = [p for p in plan if not p.get("is_appendix")]
    apps = [p for p in plan if p.get("is_appendix")]

    # 先确定每个 appendix 的目标 parent
    app_targets: dict[int, Optional[dict]] = {}  # id(app_entry) -> target normal entry
    non_app_sorted_prev = sorted(non_app, key=lambda e: e.get("toc_idx", 0))
    for app in apps:
        core = _appendix_core_tokens(app.get("title", ""))
        if not core:
            app_targets[id(app)] = None
            continue
        # 查物理前一个 non_app 的 score（用于判断 appendix 原位置是否已正确）
        a_idx = app.get("toc_idx", -1)
        prev_normal = None
        for c in non_app_sorted_prev:
            if c.get("toc_idx", 10**9) < a_idx:
                prev_normal = c
            else:
                break
        prev_score = _semantic_score(core, prev_normal.get("title", "")) if prev_normal else 0

        # 扫所有候选，找最佳
        best = None
        best_score = 0
        for c in candidates:
            s = _semantic_score(core, c.get("title", ""))
            if s > best_score:
                best_score = s
                best = c

        # 决策：
        # 1) 最佳匹配分达阈值 4，且 prev（原物理父）的分数明显低于最佳（<最佳的一半，或 < 30）
        #    → 重排到 best
        # 2) 原位置 prev_score 已够高（>= 30）→ 保持原位
        # 3) 没有好匹配 → 保持原位
        if best and best_score >= 4 and (prev_score < 30 or prev_score * 2 < best_score):
            app_targets[id(app)] = best
        else:
            app_targets[id(app)] = None

    # 组装：按 non_app 顺序遍历，每个 normal 之后插入匹配到它的 appendix
    new_plan: list[dict] = []
    pending_unmatched: list[dict] = []  # 未匹配的 appendix 按原物理位置跟随
    # 先按 non_app 的 toc_idx 分段；未匹配 appendix 挂在它物理前一个 non_app 之后
    non_app_sorted = sorted(non_app, key=lambda e: e.get("toc_idx", 0))
    # 未匹配 appendix：按原 toc_idx 找物理前一个 non_app
    fallback_after: dict[int, list[dict]] = {}  # non_app_toc_idx -> [app, ...]
    for app in apps:
        if app_targets[id(app)] is None:
            a_idx = app.get("toc_idx", -1)
            prev = None
            for c in non_app_sorted:
                if c.get("toc_idx", 10**9) < a_idx:
                    prev = c
                else:
                    break
            key = prev.get("toc_idx", -1) if prev else -1
            fallback_after.setdefault(key, []).append(app)

    # 匹配的 appendix 按 target 分组
    matched_after: dict[int, list[dict]] = {}
    for app in apps:
        tgt = app_targets[id(app)]
        if tgt is None:
            continue
        matched_after.setdefault(tgt.get("toc_idx", -1), []).append(app)

    # 输出：遍历 non_app_sorted，每条输出后追加它匹配到的 appendix
    for c in non_app_sorted:
        new_plan.append(c)
        tidx = c.get("toc_idx", -1)
        for app in matched_after.get(tidx, []):
            new_plan.append(app)
        for app in fallback_after.get(tidx, []):
            new_plan.append(app)

    return new_plan


# ---------- 统计 ----------

def summarize(plan: list[dict]) -> dict:
    from collections import Counter
    st_counter = Counter(p.get("status", "?") for p in plan)
    needs_review = [p for p in plan if p["status"] == STATUS_NEEDS_REVIEW]
    unmatched = [p for p in plan if p["status"] == STATUS_UNMATCHED]
    out_of_scope = [p for p in plan if p["status"] == STATUS_OUT_OF_SCOPE]
    return {
        "total": len(plan),
        "by_status": dict(st_counter),
        "needs_review_titles": [f"{p['chapter_no']} {p['title']}" for p in needs_review],
        "unmatched_titles": [f"{p['chapter_no']} {p['title']}" for p in unmatched],
        "out_of_scope_count": len(out_of_scope),
    }


def apply_gap_plan(plan: list[dict], gap_plan_path: Path | None) -> list[dict]:
    if not gap_plan_path or not gap_plan_path.exists():
        return plan
    data = json.loads(gap_plan_path.read_text(encoding="utf-8"))
    items = data.get("items") if isinstance(data, dict) else []
    if not isinstance(items, list):
        return plan

    by_number: dict[str, dict] = {}
    by_title: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        number = str(item.get("number") or "").strip()
        title = _normalize_title(str(item.get("title") or ""))
        if number:
            by_number[number] = item
        if title:
            by_title[title] = item
        if number and title:
            by_title[_normalize_title(f"{number} {item.get('title') or ''}")] = item

    for entry in plan:
        number = str(entry.get("chapter_no_flat") or entry.get("chapter_no") or "").strip()
        title = _normalize_title(str(entry.get("title") or ""))
        gap_item = by_number.get(number) or by_title.get(title)
        if not gap_item:
            continue
        paths = _gap_plan_paths(gap_item)
        if not paths and _gap_plan_item_is_structural(gap_item):
            entry["paths"] = []
            entry["shifts"] = []
            entry["attach_modes"] = []
            entry["status"] = STATUS_STRUCTURAL
            entry["note"] = "来自缺口识别与处理计划：结构性目录项"
            entry["gap_plan_item_id"] = str(gap_item.get("id") or "")
            continue
        if not paths:
            continue
        entry["paths"] = paths
        entry["shifts"] = [0 for _ in paths]
        entry["attach_modes"] = ["normal" for _ in paths]
        entry["status"] = STATUS_ADAPTED if entry.get("field_replace") else STATUS_MATCHED
        entry["note"] = "来自缺口识别与处理计划"
        entry["gap_plan_item_id"] = str(gap_item.get("id") or "")
    return plan


def _gap_plan_paths(item: dict) -> list[str]:
    paths: list[str] = []
    for key in ("matchedMaterials", "resolvedArtifacts"):
        values = item.get(key) or []
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, str):
                candidate = value
            elif isinstance(value, dict):
                candidate = str(value.get("path") or value.get("docx") or "")
            else:
                candidate = ""
            if candidate and candidate not in paths:
                paths.append(candidate)
    return paths


def _gap_plan_item_is_structural(item: dict) -> bool:
    status = str(item.get("status") or "").strip().lower()
    if status == "structural":
        return True
    usage = str(item.get("usage") or "").strip().lower()
    if usage == "structural":
        return True
    gap_reason = str(item.get("gapReason") or "")
    return "结构性目录项" in gap_reason


def _normalize_title(value: str) -> str:
    return re.sub(r"[\s:：，,。.！!？?\\\-_/'\"“”‘’·（）()【】\[\]/]+", "", str(value or ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--toc", type=Path, required=True)
    ap.add_argument("--wiki", type=Path, required=True, help="wiki 根目录（含 卡片/ index.md）")
    ap.add_argument("--params", type=Path, default=None, help="project_params.json（目前未用；占位）")
    ap.add_argument("--gap-plan", type=Path, default=None, help="S4 缺口识别与处理计划 JSON")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--summary", action="store_true", help="同时打印摘要到 stderr")
    args = ap.parse_args()

    toc = json.loads(args.toc.read_text(encoding="utf-8"))
    cards = load_cards(args.wiki)
    params = {}
    if args.params and args.params.exists():
        params = json.loads(args.params.read_text(encoding="utf-8"))

    plan = build_plan(toc, cards, params)
    plan = apply_gap_plan(plan, args.gap_plan)
    plan = rearrange_appendices(plan)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = summarize(plan)
    print(f"[OK] {len(plan)} entries → {args.out}", file=sys.stderr)
    print(f"[SUMMARY] {json.dumps(summary['by_status'], ensure_ascii=False)}", file=sys.stderr)
    if summary["needs_review_titles"]:
        print(f"[NEEDS_REVIEW] {len(summary['needs_review_titles'])}:", file=sys.stderr)
        for t in summary["needs_review_titles"][:10]:
            print(f"  - {t}", file=sys.stderr)
        if len(summary["needs_review_titles"]) > 10:
            print(f"  ... {len(summary['needs_review_titles']) - 10} more", file=sys.stderr)
    if summary["unmatched_titles"]:
        print(f"[UNMATCHED] {len(summary['unmatched_titles'])}:", file=sys.stderr)
        for t in summary["unmatched_titles"][:10]:
            print(f"  - {t}", file=sys.stderr)
    if args.summary:
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
