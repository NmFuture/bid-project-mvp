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

from typing import Any, Callable

# 预览缓存结构版本：仅当 prompt 或 preview 字段结构变化时升此版本，
# 让所有文件缓存指纹失效、触发重算。后端从桥接 re-export，作为指纹的一部分。
PREVIEW_SCHEMA_VERSION = 1

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
