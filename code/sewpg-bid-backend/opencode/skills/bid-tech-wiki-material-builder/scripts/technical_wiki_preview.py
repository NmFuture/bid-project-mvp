#!/usr/bin/env python3
"""技术标 Wiki 文件卡片内容预览 prompt / schema / 回复解析。"""

from __future__ import annotations

from typing import Any, Callable

PREVIEW_SCHEMA_VERSION = 1
PREVIEW_BATCH_SIZE = 8


def format_heading_tree(headings: list[dict[str, Any]], limit: int = 60) -> str:
    if not headings:
        return "未检测到 Word Heading 样式。"
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
    headings = profile.get("headings") or []
    paragraphs = profile.get("paragraphs") or []
    heading_tree = format_heading_tree(headings) if headings else "（无）"
    paragraph_block = "\n".join(f"- {p}" for p in paragraphs) if paragraphs else "（无）"
    return heading_tree, paragraph_block


_PREVIEW_SCHEMA_LINE = (
    '{"lead":"一句话导读 ≤80字，说明这份材料是什么、能用于投标哪个环节",'
    '"points":["3到5条要点，每条≤40字"],'
    '"keyParams":[{"label":"参数名","value":"参数值"}],'
    '"retrievalHints":["2到6个检索关键词或适用场景"]}'
)


def build_preview_prompt(name: str, path: str, tier_label: str, profile: dict[str, Any]) -> str:
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
    try:
        parsed = json_loader(str(reply or ""))
    except Exception:
        return None
    return _clip_preview_object(parsed)


def build_batch_preview_prompt(items: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for item in items:
        heading_tree, paragraph_block = _profile_blocks(item.get("profile") or {})
        blocks.append(
            f"### fileId: {item.get('fileId') or ''}\n"
            f"文件名：{item.get('name') or ''}\n"
            f"所在路径：{item.get('path') or ''}\n"
            f"所属档位：{item.get('tier_label') or ''}\n"
            f"检测到的标题：\n{heading_tree}\n"
            f"正文摘录（最多10段）：\n{paragraph_block}"
        )
    return (
        "你是投标素材库的资料员。下面有多份技术标素材文件的结构化摘要，"
        "每份用 `### fileId: RAW-XXXX` 分隔。请为每一份生成一张「内容预览卡片」。\n\n"
        f"{chr(10).join(blocks)}\n\n"
        "要求：\n"
        "1. 只输出严格 JSON，不要解释、不要代码块。\n"
        "2. 不要编造文中没有的事实；信息不足的字段给空数组/空串。\n"
        "3. 每份预览对象结构严格满足：\n"
        f"{_PREVIEW_SCHEMA_LINE}\n"
        '4. 顶层结构为 {"previews":{"RAW-XXXX":<预览对象>}}。'
    )


def parse_batch_preview_reply(reply: str, json_loader: Callable[[str], Any]) -> dict[str, dict[str, Any]]:
    try:
        parsed = json_loader(str(reply or ""))
    except Exception:
        return {}
    if not isinstance(parsed, dict) or not isinstance(parsed.get("previews"), dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for file_id, raw in parsed["previews"].items():
        clipped = _clip_preview_object(raw)
        if clipped is not None:
            out[str(file_id)] = clipped
    return out
