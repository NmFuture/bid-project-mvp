from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from app.services.onlyoffice_documents import document_path, write_document
from app.services.opencode_client import OpencodeClient
from app.services.outline_generation import _collect_template_hints
from app.services.store import now_iso, store

MAX_TENDER_TEXT_CHARS = 12000
MAX_TEMPLATE_HINTS = 40
ALLOWED_GENERATION_MODES = {"generated", "placeholder", "generated_with_placeholder"}


def generate_draft_for_project(project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return generate_draft_for_project_with_progress(project_id, data)


def generate_draft_for_project_with_progress(
    project_id: str,
    data: dict[str, Any] | None = None,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    project = store.get_project(project_id)
    outline_state = store.get_outline_state(project_id)
    review_state = store.get_review_items(project_id)
    parse_storage = store.get_parse_storage(project_id)
    _, template_file_records = store.get_parse_inputs(project_id)

    if outline_state.get("reviewStatus") != "confirmed":
        raise ValueError("请先在 S3 完成目录确认后再触发 S7 填充。")
    if not review_state.get("confirmed"):
        raise ValueError("请先在 S6 完成审核确认后再触发 S7 填充。")

    combined_text_path = Path(str(parse_storage.get("combinedTextPath") or ""))
    if not combined_text_path.exists():
        raise ValueError("S1 解析结果不存在，请先完成解析。")

    combined_text = combined_text_path.read_text(encoding="utf-8").strip()
    if not combined_text:
        raise ValueError("S1 解析文本为空，暂时无法生成初稿。")

    top_level_nodes = list(outline_state.get("nodes") or [])
    if not top_level_nodes:
        raise ValueError("S3 当前目录为空，暂时无法生成初稿。")

    template_hints = _collect_template_hints(template_file_records)
    prompt = _build_draft_prompt(
        project_name=str(project.get("name") or project_id),
        tender_excerpt=combined_text[:MAX_TENDER_TEXT_CHARS],
        outline_nodes=top_level_nodes,
        template_hints=template_hints,
        review_state=review_state,
        options=data or {},
    )
    if progress_callback:
        progress_callback(
            "inputs_ready",
            {
                "sectionCount": len(top_level_nodes),
                "templateHintCount": len(template_hints),
            },
        )

    started_at = time.monotonic()
    result = OpencodeClient().generate_draft_sections_with_trace(
        prompt,
        session_ready_callback=(
            lambda meta: progress_callback("calling_opencode", meta) if progress_callback else None
        ),
    )
    run_duration_sec = max(1, int(round(time.monotonic() - started_at)))

    sections = _normalize_sections(result.get("sections") or [], top_level_nodes)
    if progress_callback:
        progress_callback(
            "assembling_result",
            {
                "sectionCount": len(sections),
            },
        )
    summary = str(result.get("summary") or "初稿生成完成。")
    content = _build_document_content(project_name=str(project.get("name") or project_id), sections=sections)

    file_name = f"{project['name']}_初稿.docx"
    target_path = document_path(project_id)
    write_document(target_path, file_name, content)
    file_size_bytes = target_path.stat().st_size if target_path.exists() else 0

    return store.save_fill_generation_result(
        project_id=project_id,
        summary=summary,
        sections=sections,
        content=content,
        filled_at=now_iso(),
        run_duration_sec=run_duration_sec,
        file_size_bytes=file_size_bytes,
        opencode_output=result.get("opencodeOutput"),
    )


def _build_draft_prompt(
    project_name: str,
    tender_excerpt: str,
    outline_nodes: list[dict[str, Any]],
    template_hints: list[str],
    review_state: dict[str, Any],
    options: dict[str, Any],
) -> str:
    outline_text = json.dumps(_outline_for_prompt(outline_nodes), ensure_ascii=False, indent=2)
    template_hint_text = "\n".join(f"- {item}" for item in template_hints[:MAX_TEMPLATE_HINTS]) or "- 当前没有模板章节线索"
    review_summary = _build_review_summary(review_state)
    tone = str(options.get("tone") or "正式、稳健、适合技术标初稿")

    return f"""
Use the bid-draft-sections-json skill.

你现在在做技术标 MVP 的 S7 初稿生成，请直接输出一个“可编辑、可继续补充”的初稿 JSON。

项目名称：{project_name}
行文风格：{tone}

只返回 JSON，不要返回解释文字，不要使用 Markdown 代码块。
返回格式必须是：
{{
  "summary": "一句简短总结",
  "sections": [
    {{
      "nodeId": "OL-1",
      "title": "章节标题",
      "generationMode": "generated",
      "content": "章节正文，允许使用 Markdown 标题和段落",
      "riskFlags": []
    }}
  ]
}}

规则：
1. `sections` 必须严格按一级目录顺序返回，一章对应一个 section，不要新增或删除章节。
2. `generationMode` 只能是 `generated`、`placeholder`、`generated_with_placeholder`。
3. 每个一级章节最多写 2 段，最多 1 个 `##` 小节，内容保持简洁，不要写成长篇大论。
4. 涉及业绩、参数、证书编号、金额、日期、人数等可核验事实时，不能编造；缺少信息就写 `【待补充：...】`。
5. 需要补充事实时，把 `generationMode` 设为 `generated_with_placeholder` 或 `placeholder`，并在 `riskFlags` 中写 `FACT_REQUIRED`。
6. 不要输出素材库、数据库、后期拼接、系统实现说明等无关内容，只生成投标文件初稿正文。

已确认目录（一级节点为主，children 是该章下的子章节线索）：
{outline_text}

投标模板章节线索：
{template_hint_text}

S6 审核结果摘要：
{review_summary}

招标文本摘要：
{tender_excerpt}
""".strip()


def _outline_for_prompt(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": str(node.get("id") or ""),
            "title": str(node.get("title") or "").strip(),
            "children": _outline_for_prompt(node.get("children") or []),
        }
        for node in nodes
    ]


def _build_review_summary(review_state: dict[str, Any]) -> str:
    items = list(review_state.get("items") or [])
    if not items:
        return "- 当前没有补料审核结果"

    lines = [
        f"- 审核确认：{'是' if review_state.get('confirmed') else '否'}",
        f"- 总项数：{len(items)}",
    ]
    for item in items[:8]:
        title = str(item.get("title") or "未命名条目")
        section = str(item.get("section") or "")
        status = str(item.get("status") or "unknown")
        lines.append(f"- {title}（{section}）：{status}")
    if len(items) > 8:
        lines.append(f"- 其余 {len(items) - 8} 项省略")
    return "\n".join(lines)


def _normalize_sections(
    raw_sections: list[dict[str, Any]],
    outline_nodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {
        str(item.get("nodeId") or "").strip(): item
        for item in raw_sections
        if str(item.get("nodeId") or "").strip()
    }
    by_title = {
        str(item.get("title") or "").strip(): item
        for item in raw_sections
        if str(item.get("title") or "").strip()
    }

    normalized: list[dict[str, Any]] = []
    for node in outline_nodes:
        node_id = str(node.get("id") or "").strip()
        title = str(node.get("title") or "").strip() or node_id or "未命名章节"
        raw = by_id.get(node_id) or by_title.get(title) or {}

        generation_mode = str(raw.get("generationMode") or "").strip()
        if generation_mode not in ALLOWED_GENERATION_MODES:
            generation_mode = "placeholder"

        content = str(raw.get("content") or "").strip()
        if not content:
            content = _default_placeholder_content(title, node.get("children") or [])
            generation_mode = "placeholder"

        risk_flags = [
            str(flag).strip()
            for flag in (raw.get("riskFlags") or [])
            if str(flag).strip()
        ]
        if generation_mode != "generated" and "FACT_REQUIRED" not in risk_flags:
            risk_flags.append("FACT_REQUIRED")

        normalized.append(
            {
                "nodeId": node_id,
                "title": title,
                "generationMode": generation_mode,
                "content": content,
                "riskFlags": risk_flags,
            }
        )
    return normalized


def _default_placeholder_content(title: str, children: list[dict[str, Any]]) -> str:
    if children:
        lines: list[str] = []
        for child in children:
            child_title = str(child.get("title") or "").strip() or "未命名小节"
            lines.append(f"## {child_title}")
            lines.append(f"【待补充：{child_title}】")
            lines.append("")
        return "\n".join(lines).strip()
    return f"【待补充：{title}】"


def _build_document_content(project_name: str, sections: list[dict[str, Any]]) -> str:
    lines = [f"# {project_name} 初稿", ""]
    for section in sections:
        title = str(section.get("title") or "未命名章节").strip()
        content = str(section.get("content") or "").strip() or f"【待补充：{title}】"
        lines.append(f"# {title}")
        lines.append("")
        lines.extend(content.splitlines())
        lines.append("")
    return "\n".join(lines).strip()
