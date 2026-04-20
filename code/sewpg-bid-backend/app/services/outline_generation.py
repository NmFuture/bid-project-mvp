from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree as ET

from app.services.opencode_client import OpencodeClient
from app.services.store import build_directory_opencode_output, now_iso, store

WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MAX_TENDER_TEXT_CHARS = 1200
MAX_TENDER_HINTS = 12
MAX_TEMPLATE_HINTS = 12
MAX_FALLBACK_ERROR_PREVIEW_CHARS = 200

HEADING_PATTERNS = [
    re.compile(r"^第[一二三四五六七八九十百千0-9]+章[\s　].+"),
    re.compile(r"^第[一二三四五六七八九十百千0-9]+章.+"),
    re.compile(r"^[一二三四五六七八九十百千]+、.+"),
    re.compile(r"^\d+(\.\d+){0,3}[\s　].+"),
    re.compile(r"^附表[0-9一二三四五六七八九十]+.+"),
]


def generate_outline_for_project(project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return generate_outline_for_project_with_progress(project_id, data)


def generate_outline_for_project_with_progress(
    project_id: str,
    data: dict[str, Any] | None = None,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    project = store.get_project(project_id)
    parse_storage = store.get_parse_storage(project_id)
    _, template_file_records = store.get_parse_inputs(project_id)
    combined_text_path = Path(str(parse_storage.get("combinedTextPath") or ""))
    if not combined_text_path.exists():
        raise ValueError("S1 解析结果不存在，请先完成解析。")

    combined_text = combined_text_path.read_text(encoding="utf-8").strip()
    if not combined_text:
        raise ValueError("S1 解析文本为空，暂时无法生成目录。")

    tender_hints = _extract_heading_candidates(combined_text, MAX_TENDER_HINTS)
    template_hints = _collect_template_hints(template_file_records)
    if progress_callback:
        progress_callback(
            "inputs_ready",
            {
                "tenderHintCount": len(tender_hints),
                "templateHintCount": len(template_hints),
            },
        )

    options = data or {}
    prompt = _build_outline_prompt(
        project_name=str(project.get("name") or project_id),
        outline_strategy=str(options.get("outlineStrategy") or "strict"),
        include_key_points=bool(options.get("includeKeyPoints", True)),
        tender_excerpt=combined_text[:MAX_TENDER_TEXT_CHARS],
        tender_hints=tender_hints,
        template_hints=template_hints,
    )

    client = OpencodeClient()
    used_fallback = False
    fallback_error = ""
    try:
        result = client.generate_outline_with_trace(
            prompt,
            session_ready_callback=(
                (lambda details: progress_callback("calling_opencode", details))
                if progress_callback
                else None
            ),
        )
        nodes = _normalize_nodes(result["nodes"])
        summary = str(result.get("summary") or "目录生成完成。")
        opencode_output = result.get("opencodeOutput") or {}
    except RuntimeError as exc:
        used_fallback = True
        fallback_error = str(exc)
        fallback_error_text = _shorten_for_event(fallback_error)
        nodes = _build_outline_fallback_nodes(
            project_name=str(project.get("name") or project_id),
            tender_hints=tender_hints,
            template_hints=template_hints,
        )
        summary = (
            f"opencode 响应异常（{fallback_error_text}），已根据模板与招标章节线索生成回退目录。"
        )
        opencode_output = build_directory_opencode_output(
            status="failed",
            parts=[
                {
                    "type": "text",
                    "text": f"opencode 响应异常：{fallback_error}",
                }
            ],
        )
    if progress_callback:
        progress_callback(
            "normalizing_result",
            {
                "chapterCount": len(nodes),
            },
        )

    generated_at = now_iso()
    payload = store.save_generated_outline(
        project_id=project_id,
        nodes=nodes,
        generated_at=generated_at,
        summary=summary,
        opencode_output=opencode_output,
    )
    if used_fallback:
        payload = store.update_directory_generation_state(
            project_id,
            event_message=f"opencode 响应异常（{_shorten_for_event(fallback_error)}），已切换为本地回退目录。",
            event_level="warning",
            event_step="fallback",
            opencode_output={
                "status": "failed",
                "parts": [
                    {
                        "type": "text",
                        "text": f"回退原因：{_shorten_for_event(fallback_error, limit=340)}",
                    }
                ],
            },
        )
    return payload


def _shorten_for_event(message: str, limit: int = MAX_FALLBACK_ERROR_PREVIEW_CHARS) -> str:
    text = str(message or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text or "未知错误"
    return f"{text[: limit - 3]}..."


def _collect_template_hints(template_file_records: list[dict[str, Any]]) -> list[str]:
    hints: list[str] = []
    for file_record in template_file_records:
        path = Path(str(file_record.get("path") or ""))
        if not path.exists():
            continue
        if path.suffix.lower() == ".docx":
            hints.extend(_extract_docx_outline_hints(path, MAX_TEMPLATE_HINTS))
        if len(hints) >= MAX_TEMPLATE_HINTS:
            break
    seen: set[str] = set()
    ordered: list[str] = []
    for item in hints:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
        if len(ordered) >= MAX_TEMPLATE_HINTS:
            break
    return ordered


def _extract_docx_outline_hints(path: Path, limit: int) -> list[str]:
    hints: list[str] = []
    current_parts: list[str] = []

    def flush_paragraph() -> None:
        line = "".join(current_parts).strip()
        current_parts.clear()
        if not line:
            return
        if _looks_like_heading(line):
            hints.append(line)

    with zipfile.ZipFile(path) as archive:
        with archive.open("word/document.xml") as xml_file:
            for _, element in ET.iterparse(xml_file, events=("end",)):
                if element.tag == f"{WORD_NAMESPACE}t":
                    current_parts.append(element.text or "")
                elif element.tag == f"{WORD_NAMESPACE}tab":
                    current_parts.append(" ")
                elif element.tag in {f"{WORD_NAMESPACE}br", f"{WORD_NAMESPACE}cr"}:
                    current_parts.append(" ")
                elif element.tag == f"{WORD_NAMESPACE}p":
                    flush_paragraph()
                    element.clear()
                if len(hints) >= limit:
                    break
    return hints[:limit]


def _extract_heading_candidates(text: str, limit: int) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not _looks_like_heading(line):
            continue
        if line in seen:
            continue
        seen.add(line)
        candidates.append(line)
        if len(candidates) >= limit:
            break
    return candidates


def _looks_like_heading(line: str) -> bool:
    if not line:
        return False
    if len(line) > 80:
        return False
    for pattern in HEADING_PATTERNS:
        if pattern.match(line):
            return True
    return False


def _build_outline_prompt(
    project_name: str,
    outline_strategy: str,
    include_key_points: bool,
    tender_excerpt: str,
    tender_hints: list[str],
    template_hints: list[str],
) -> str:
    tender_hint_text = "\n".join(f"- {item}" for item in tender_hints) or "- 无明显章节线索"
    template_hint_text = "\n".join(f"- {item}" for item in template_hints) or "- 当前没有模板章节线索"
    include_key_points_text = "是" if include_key_points else "否"

    return f"""
Use the bid-outline-json skill.

你现在在做技术标 MVP 的 S2 目录生成，请输出一个可直接给前端 S3 编辑的目录 JSON。

项目名称：{project_name}
目录策略：{outline_strategy}
是否尽量包含关键评分点：{include_key_points_text}

请先按投标模板目录起基础目录，再对照招标要求删改、补改。

只返回 JSON，不要返回解释文字，不要使用 Markdown 代码块。
返回格式必须是：
{{
  "summary": "一句简短总结",
  "nodes": [
    {{
      "id": "OL-1",
      "title": "一级标题",
      "children": [
        {{
          "id": "OL-1-1",
          "title": "二级标题",
          "children": []
        }}
      ]
    }}
  ]
}}

规则：
1. 目录层级最多 3 层。
2. 标题要简洁，适合中文技术标目录。
3. 目录必须以投标模板目录为主骨架，再根据招标要求重命名、删除不适用章节、补充遗漏章节。
4. 不要编造公司业绩、参数或事实内容，这里只生成目录结构。
5. 至少生成 3 个一级节点。

招标章节线索：
{tender_hint_text}

投标模板章节线索：
{template_hint_text}

招标正文摘录（仅前段关键信息）：
{tender_excerpt}
""".strip()


def _normalize_nodes(nodes: list[dict[str, Any]], prefix: str = "OL") -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, node in enumerate(nodes, start=1):
        node_id = f"{prefix}-{index}"
        children = _normalize_children(node.get("children") or [], node_id)
        normalized.append(
            {
                "id": node_id,
                "title": str(node.get("title") or "").strip() or f"未命名章节{index}",
                "children": children,
            }
        )
    return normalized


def _build_outline_fallback_nodes(
    project_name: str,
    tender_hints: list[str],
    template_hints: list[str],
) -> list[dict[str, Any]]:
    candidates = [*_extract_primary_titles(template_hints), *_extract_primary_titles(tender_hints)]
    seen: set[str] = set()
    titles: list[str] = []
    for title in candidates:
        normalized = title.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        titles.append(normalized)
        if len(titles) >= 5:
            break

    defaults = ["项目概况", "技术方案", "实施与保障"]
    for title in defaults:
        if title not in seen:
            titles.append(title if title != "技术方案" else f"{project_name}技术方案")
            seen.add(title)
        if len(titles) >= 3:
            break

    if len(titles) < 3:
        titles.extend([f"{project_name}目录章节{index}" for index in range(len(titles) + 1, 4)])

    return [
        {
            "id": f"OL-{index}",
            "title": title,
            "children": [],
        }
        for index, title in enumerate(titles[:5], start=1)
    ]


def _extract_primary_titles(hints: list[str]) -> list[str]:
    titles: list[str] = []
    for line in hints:
        text = re.sub(r"[（(][^）)]*[）)]\s*$", "", line).strip()
        if not text:
            continue
        if re.match(r"^第[一二三四五六七八九十百千0-9]+章", text):
            titles.append(re.sub(r"^第[一二三四五六七八九十百千0-9]+章[\s　]*", "", text).strip())
            continue
        if re.match(r"^[一二三四五六七八九十]+、", text):
            titles.append(re.sub(r"^[一二三四五六七八九十]+、", "", text).strip())
            continue
    return titles


def _normalize_children(nodes: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, node in enumerate(nodes, start=1):
        node_id = f"{prefix}-{index}"
        children = _normalize_children(node.get("children") or [], node_id)
        normalized.append(
            {
                "id": node_id,
                "title": str(node.get("title") or "").strip() or f"未命名章节{index}",
                "children": children,
            }
        )
    return normalized
