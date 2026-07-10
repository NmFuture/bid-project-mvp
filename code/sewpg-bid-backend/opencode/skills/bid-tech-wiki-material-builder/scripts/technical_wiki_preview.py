#!/usr/bin/env python3
"""技术标 Wiki 文件卡片 AI 内容预览：prompt 模板 / 输出 schema / 回复解析。

本模块是 `bid-tech-wiki-material-builder` skill 的资产，承载预览生成的 prompt
规则与解析规则，供后端复用（后端通过 importlib 桥接 import，见
`app/services/technical_wiki_preview_prompt.py`）。

设计约束：
- **纯 stdlib，零 `app.*` 依赖**（与 business_wiki_blueprint.py 同款，才能被后端
  importlib 加载而不引入循环依赖）。
- JSON 解析用**依赖注入**：调用方把 json_loader（如 OpencodeClient._parse_json_payload）
  传进来，本模块不直接 import 后端的解析器。
- 预览仍由**后端发请求 + 控制缓存/并发**；本模块只提供「怎么问、怎么读」，不挂
  opencode agent 逐文件编排。

单文件与批量两套：
- 单文件 build/parse 用于 fallback 或 BATCH_SIZE=1 退化场景。
- 批量 build/parse 把多份文件摘要合进一次 LLM 调用、按 fileId(RAW-NNNN) 拆回，
  把「几百次调用」降到「几十次」。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Callable

# 预览缓存结构版本：仅当 prompt 或 preview 字段结构变化时升此版本，
# 让所有文件缓存指纹失效、触发重算。后端从桥接 re-export，作为指纹的一部分。
# v2：预览对象新增 evidenceSegments（段落级证据片段），供非附表正文缺口召回。
# v3：片段新增 topicKeywords（文件名+目录+heading 抽的主题词），供主题级弱关联召回。
PREVIEW_SCHEMA_VERSION = 3

# 批量合并：一次 LLM 调用喂多少份文件摘要。把请求数从「文件数」降到「文件数/BATCH」。
PREVIEW_BATCH_SIZE = 8


def format_heading_tree(headings: list[dict[str, Any]], limit: int = 60) -> str:
    """把 docx heading 列表渲染成缩进树（从 wiki_blueprint_common 复制以保持本模块独立）。"""
    if not headings:
        return "未检测到 Word Heading 样式；该素材会按整篇材料挂载，后续应补充 Heading 样式审计。"
    min_level = min(int(item.get("level") or 1) for item in headings)
    lines: list[str] = []
    for item in headings[:limit]:
        level = int(item.get("level") or 1)
        indent = "  " * max(0, level - min_level)
        lines.append(f"{indent}- L{level} {item.get('title')}")
    if len(headings) > limit:
        lines.append(f"- ... 另有 {len(headings) - limit} 条 Heading")
    return "\n".join(lines)


def _profile_blocks(profile: dict[str, Any]) -> tuple[str, str]:
    """从 docx profile 抽出 heading 树文本和正文摘录块（单/批共用）。"""
    headings = profile.get("headings") or []
    paragraphs = profile.get("paragraphs") or []
    heading_tree = format_heading_tree(headings) if headings else "（无）"
    paragraph_block = "\n".join(f"- {p}" for p in paragraphs) if paragraphs else "（无）"
    return heading_tree, paragraph_block


# ---------------------------------------------------------------------------
# 证据片段（evidenceSegments）确定性切分
#
# 镜像/预览这条线本就有每份 docx 的结构化 profile（headings + paragraphs，见
# wiki_blueprint_common.extract_docx_profile）。这里**不额外调 LLM、不再下载文件**，
# 直接把已抽出的 heading 树切成段落级证据片段，供 planner 的「非附表正文缺口」召回。
#
# 设计与商务标 business_gap_planning 的段落切分对齐（segmentId/title/sourcePages/
# summary/keywords），但**在技术标线内独立实现、纯 stdlib**，不抽公共函数、不碰商务标。
# 切分基于 profile，故只是「heading 级」粒度；更细的 OCR/页码后续可在此扩展。
# ---------------------------------------------------------------------------

# 技术标素材文件名/标题里的领域检索词（基于真实素材库高频词归纳，见方案 §2）。
_TECH_SEGMENT_MARKERS = (
    "型式认证", "部件证书", "部件型式认证", "螺栓在线监测", "在线振动监测",
    "叶片净空监测", "自动消防系统", "质量保证", "质量保障", "产品交付",
    "考核及验收", "标方案", "设备运行和维护", "技术服务", "售后服务",
    "混塔", "钢塔", "塔筒", "电网友好性", "碳排放", "智能场控", "智能控制",
    "智能监控", "智能运维", "智能终端", "风功率预测", "生产能力", "试验检测",
    "整机抗涡激", "并网", "载荷", "传动链", "发电机", "变流器", "齿轮箱", "叶片",
    "试验", "检验", "监造", "型式试验", "安装", "调试", "试运行", "吊装",
    "运输", "交付进度", "技术资料", "验收", "质保", "可利用率", "功率曲线",
    "发电量", "等效满负荷", "承诺函", "供货范围", "运维",
)

# 单份素材最多切出的片段数（与商务标一致，控制 planner 候选规模）。
_MAX_SEGMENTS_PER_MATERIAL = 24
# 片段摘要上限字数。
_SEGMENT_SUMMARY_LIMIT = 240

# 关键词噪声词：路径骨架/扩展名/无区分度的词，不作为检索关键词。
_SEGMENT_KEYWORD_STOPWORDS = frozenset({
    "技术标", "通用素材", "客户素材", "项目素材", "标准文件", "客户定制", "项目定制",
    "docx", "doc", "pdf", "xlsx", "xls", "上置", "下置", "待填写",
})


def _stable_short_id(value: str) -> str:
    text = str(value or "").strip() or "segment"
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _segment_keywords(text: str) -> list[str]:
    """从路径/标题里拆词 + 命中领域 marker，作为片段检索关键词。

    过滤掉路径骨架/扩展名等无区分度的停用词；机型号（EW…）等具体标识保留。
    """
    raw = str(text or "")
    candidates = [
        item for item in re.split(r"[/_\-\s　.。；;，,、（）()【】\\]+", raw)
        if len(item) >= 2 and item not in _SEGMENT_KEYWORD_STOPWORDS
    ]
    for marker in _TECH_SEGMENT_MARKERS:
        if marker in raw:
            candidates.append(marker)
    return _dedupe_strings(candidates)[:24]


def build_evidence_segments(material_id: str, name: str, path: str, profile: dict[str, Any]) -> list[dict[str, Any]]:
    """把一份 docx 的结构化 profile 切成段落级证据片段（确定性，不调 LLM）。

    切分策略（由细到粗，逐级回退）：
    1. 有 heading：按 heading 切，标题=heading 文本，摘要取其后正文摘录里最相关的几段。
    2. 无 heading 但有正文摘录：整篇正文摘录合成一个 file_fallback 片段。
    3. 都没有：返回空（上层不挂 evidenceSegments，仍可按文件名匹配）。

    每个片段 schema：
      {segmentId, materialId, title, segmentScope, sourcePages, summary, keywords, topicKeywords}

    topicKeywords：素材级主题词（文件名 + 三级目录名 + 全部 heading 抽词），供
    planner 做「主题相关但文件名对不上」的弱关联召回；同一素材所有片段共享同一份。
    """
    mid = str(material_id or "").strip()
    base_title = str(name or "").rsplit(".", 1)[0] or str(name or "") or mid
    headings = [h for h in (profile.get("headings") or []) if isinstance(h, dict)]
    paragraphs = [str(p or "").strip() for p in (profile.get("paragraphs") or []) if str(p or "").strip()]

    # 素材级主题词：文件名 + 路径（含机型/分类目录）+ 全部 heading 标题，统一抽词。
    heading_text = " ".join(str(h.get("title") or "") for h in headings)
    topic_keywords = _segment_keywords(f"{path}/{base_title}/{heading_text}")

    segments: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def _push(title: str, scope: str, source_pages: str, summary: str) -> None:
        title = str(title or "").strip()[:80] or base_title
        seg_id = f"tech-seg-{_stable_short_id(f'{mid}:{title}:{len(segments)}')}"
        while seg_id in seen_ids:
            seg_id = f"{seg_id}-{_stable_short_id(f'{seg_id}:{len(segments)}')[:4]}"
        seen_ids.add(seg_id)
        segments.append({
            "segmentId": seg_id,
            "materialId": mid,
            "title": title,
            "segmentScope": scope,
            "sourcePages": source_pages,
            "summary": re.sub(r"\s+", " ", str(summary or "")).strip()[:_SEGMENT_SUMMARY_LIMIT],
            "keywords": _segment_keywords(f"{path}/{title}"),
            "topicKeywords": topic_keywords,
        })

    if headings:
        # heading 级切分：标题来自 heading，摘要用紧随其后的正文摘录（profile 已是摘录，
        # 顺序近似原文），按出现顺序轮流分配，保证每个 heading 至少有一句导读。
        para_pool = list(paragraphs)
        for idx, head in enumerate(headings[:_MAX_SEGMENTS_PER_MATERIAL], start=1):
            title = str(head.get("title") or "").strip()
            if not title:
                continue
            summary = para_pool.pop(0) if para_pool else title
            _push(title, "heading_section", f"标题段{idx}", summary)
        # 正文摘录有剩余且 heading 较少时，把剩余摘录并成一个补充片段，避免信息丢失。
        if para_pool and len(segments) < _MAX_SEGMENTS_PER_MATERIAL:
            _push(base_title, "paragraph_overflow", "正文摘录", " ".join(para_pool))
    elif paragraphs:
        _push(base_title, "file_fallback", "整件/待定位", " ".join(paragraphs))

    return segments[:_MAX_SEGMENTS_PER_MATERIAL]


_PREVIEW_SCHEMA_LINE = (
    '{"lead":"一句话导读 ≤80字，说明这份材料是什么、能用于投标哪个环节",'
    '"points":["3到5条要点，每条≤40字"],'
    '"keyParams":[{"label":"参数名","value":"参数值"}],'
    '"retrievalHints":["2到6个检索关键词或适用场景"]}'
)


def build_preview_prompt(name: str, path: str, tier_label: str, profile: dict[str, Any]) -> str:
    """单文件预览 prompt（fallback / BATCH_SIZE=1 退化用）。"""
    heading_tree, paragraph_block = _profile_blocks(profile)
    return (
        "你是投标素材库的资料员。下面是一份技术标素材文件的结构化摘要，"
        "请生成一张「内容预览卡片」。\n\n"
        f"文件名：{name}\n"
        f"所在路径：{path}\n"
        f"所属档位：{tier_label}\n"
        f"检测到的标题：\n{heading_tree}\n"
        f"正文摘录（最多10段）：\n{paragraph_block}\n\n"
        "要求：\n"
        "1. 只输出严格 JSON，不要解释、不要代码块。\n"
        "2. 不要编造文中没有的事实；信息不足的字段给空数组/空串。\n"
        "3. 结构严格满足：\n"
        f"{_PREVIEW_SCHEMA_LINE}"
    )


def _clip_preview_object(parsed: Any) -> dict[str, Any] | None:
    """把单张预览对象裁剪到约定上限；无 lead 且无 points 视为无效（返回 None）。"""
    if not isinstance(parsed, dict):
        return None

    lead = str(parsed.get("lead") or "").strip()[:120]

    points: list[str] = []
    for item in parsed.get("points") or []:
        text = str(item or "").strip()
        if text:
            points.append(text[:80])
        if len(points) >= 5:
            break

    key_params: list[dict[str, str]] = []
    for kv in parsed.get("keyParams") or []:
        if not isinstance(kv, dict):
            continue
        label = str(kv.get("label") or "").strip()[:40]
        value = str(kv.get("value") or "").strip()[:120]
        if label or value:
            key_params.append({"label": label, "value": value})
        if len(key_params) >= 8:
            break

    hints: list[str] = []
    for item in parsed.get("retrievalHints") or []:
        text = str(item or "").strip()
        if text:
            hints.append(text[:40])
        if len(hints) >= 6:
            break

    if not lead and not points:
        return None

    return {
        "lead": lead,
        "points": points,
        "keyParams": key_params,
        "retrievalHints": hints,
    }


def parse_preview_reply(reply: str, json_loader: Callable[[str], Any]) -> dict[str, Any] | None:
    """把单文件 LLM 回复解析成裁剪后的 preview 子对象；无有效内容返回 None。

    json_loader：调用方注入的 JSON 解析器（如 OpencodeClient._parse_json_payload），
    本模块不直接依赖后端解析实现。
    """
    try:
        parsed = json_loader(str(reply or ""))
    except Exception:  # noqa: BLE001 - 解析失败按降级处理
        return None
    return _clip_preview_object(parsed)


def build_batch_preview_prompt(items: list[dict[str, Any]]) -> str:
    """批量预览 prompt：一次喂多份文件摘要，要求模型按 fileId 回填映射。

    items 每项：{fileId(RAW-NNNN), name, path, tier_label, profile}。
    """
    blocks: list[str] = []
    for item in items:
        file_id = str(item.get("fileId") or "")
        heading_tree, paragraph_block = _profile_blocks(item.get("profile") or {})
        blocks.append(
            f"### fileId: {file_id}\n"
            f"文件名：{item.get('name') or ''}\n"
            f"所在路径：{item.get('path') or ''}\n"
            f"所属档位：{item.get('tier_label') or ''}\n"
            f"检测到的标题：\n{heading_tree}\n"
            f"正文摘录（最多10段）：\n{paragraph_block}"
        )
    files_block = "\n\n".join(blocks)
    return (
        "你是投标素材库的资料员。下面有多份技术标素材文件的结构化摘要，"
        "每份用 `### fileId: RAW-XXXX` 分隔。请为每一份生成一张「内容预览卡片」。\n\n"
        f"{files_block}\n\n"
        "要求：\n"
        "1. 只输出严格 JSON，不要解释、不要代码块。\n"
        "2. 不要编造文中没有的事实；信息不足的字段给空数组/空串。\n"
        "3. 每份的预览对象结构严格满足：\n"
        f"{_PREVIEW_SCHEMA_LINE}\n"
        "4. 顶层用 fileId 作 key 回填，结构为：\n"
        '{"previews":{"RAW-XXXX":<预览对象>, "RAW-YYYY":<预览对象>}}\n'
        "5. previews 里必须覆盖上面出现的每一个 fileId；某份信息不足也要给出对象（字段可留空）。"
    )


def parse_batch_preview_reply(reply: str, json_loader: Callable[[str], Any]) -> dict[str, dict[str, Any]]:
    """把批量 LLM 回复解析成 {fileId: 裁剪后 preview 子对象}。

    逐 fileId 独立裁剪：某份缺失/无效则不出现在结果里（上层据此标 failed，不影响同批其他份）。
    解析整体失败返回空 dict。
    """
    try:
        parsed = json_loader(str(reply or ""))
    except Exception:  # noqa: BLE001 - 解析失败按降级处理
        return {}
    if not isinstance(parsed, dict):
        return {}
    previews = parsed.get("previews")
    if not isinstance(previews, dict):
        return {}

    out: dict[str, dict[str, Any]] = {}
    for file_id, raw in previews.items():
        key = str(file_id or "").strip()
        if not key:
            continue
        clipped = _clip_preview_object(raw)
        if clipped is not None:
            out[key] = clipped
    return out
