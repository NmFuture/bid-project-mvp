from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree as ET

from app.core.config import settings
from app.services.directory_templates import select_directory_template_profiles
from app.services.identity import build_project_identity
from app.services.opencode_client import OpencodeClient
from app.services.store import build_directory_opencode_output, now_iso, store

WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MAX_TENDER_TEXT_CHARS = 1200
MAX_TENDER_HINTS = 12
MAX_TEMPLATE_HINTS = 12
MAX_FALLBACK_ERROR_PREVIEW_CHARS = 200
TOC_SKILL_NAME = "bid-toc-wiki-driven-v2"
TOC_SKILL_COMMAND = "s2toc"

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
    tender_file_records, template_file_records = store.get_parse_inputs(project_id)
    combined_text_path = Path(str(parse_storage.get("combinedTextPath") or ""))
    if not combined_text_path.exists():
        raise ValueError("S1 解析结果不存在，请先完成解析。")

    combined_text = combined_text_path.read_text(encoding="utf-8").strip()
    if not combined_text:
        raise ValueError("S1 解析文本为空，暂时无法生成目录。")

    tender_hints = _extract_heading_candidates(combined_text, MAX_TENDER_HINTS)
    template_hints = _collect_template_hints(template_file_records)
    skill_workspace = _prepare_toc_skill_workspace(
        project_id=project_id,
        project=project,
        parse_storage=parse_storage,
        tender_file_records=tender_file_records,
        template_file_records=template_file_records,
    )
    if progress_callback:
        progress_callback(
            "inputs_ready",
            {
                "tenderHintCount": len(tender_hints),
                "templateHintCount": len(template_hints),
                "workDir": skill_workspace["workDir"],
                "bidType": skill_workspace["bidType"],
                "directoryTemplateCount": skill_workspace.get("directoryTemplateCount", 0),
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
        skill_workspace=skill_workspace,
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
            stream_callback=(
                (lambda details: progress_callback("opencode_delta", details))
                if progress_callback
                else None
            ),
        )
        toc_result = _resolve_toc_generation_result(result, skill_workspace)
        nodes = _nodes_from_generation_result(toc_result)
        summary = _summary_from_generation_result(toc_result)
        opencode_output = result.get("opencodeOutput") or {}
        opencode_output.update(
            {
                "skill": TOC_SKILL_NAME,
                "workDir": skill_workspace["workDir"],
                "manifestPath": skill_workspace["manifestPath"],
                "canonicalManifestPath": skill_workspace["canonicalManifestPath"],
                "tocJsonPath": str(toc_result.get("outputFile") or skill_workspace["outputFile"]),
            }
        )
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
            f"futurecode 响应异常（{fallback_error_text}），已根据模板与招标章节线索生成回退目录。"
        )
        opencode_output = build_directory_opencode_output(
            status="failed",
            parts=[
                {
                    "type": "text",
                    "text": f"futurecode 响应异常：{fallback_error}",
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
            event_message=f"futurecode 响应异常（{_shorten_for_event(fallback_error)}），已切换为本地回退目录。",
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


def _prepare_toc_skill_workspace(
    *,
    project_id: str,
    project: dict[str, Any],
    parse_storage: dict[str, Any],
    tender_file_records: list[dict[str, Any]],
    template_file_records: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_project_dir = str(parse_storage.get("projectDir") or "").strip()
    project_dir = Path(raw_project_dir).expanduser() if raw_project_dir else settings.parsed_dir / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    work_dir = project_dir / "s2_toc_workdir"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    tender_paths = _copy_tender_inputs(tender_file_records, work_dir)
    template_path, attach_path = _copy_template_inputs(template_file_records, work_dir)
    bid_type = _normalize_bid_type(str(project.get("bidType") or "技术标"))
    directory_templates = select_directory_template_profiles({**project, "bidType": bid_type})
    wiki_dir = work_dir / "wiki"
    output_file = work_dir / "投标文件-总目录.json"
    manifest_path = work_dir / "s2_input.json"
    manifest_alias_path = project_dir / "s2.json"
    manifest = {
        "projectId": project_id,
        "projectCode": str(project.get("projectCode") or project_id),
        "projectName": str(project.get("name") or project_id),
        "bidType": bid_type,
        "projectIdentity": build_project_identity(project),
        "workDir": str(work_dir),
        "apiBaseUrl": settings.bid_internal_api_base_url or "http://fastapi:8000",
        "tenderFiles": [
            {
                "name": item.name,
                "path": str(item),
            }
            for item in tender_paths
        ],
        "templateFile": str(template_path) if template_path else "",
        "attachFile": str(attach_path) if attach_path else "",
        "directoryTemplates": directory_templates,
        "wikiDir": str(wiki_dir),
        "outputFile": str(output_file),
    }
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2)
    manifest_path.write_text(manifest_text, encoding="utf-8")
    manifest_alias_path.write_text(manifest_text, encoding="utf-8")
    return {
        **manifest,
        "manifestPath": str(manifest_alias_path),
        "canonicalManifestPath": str(manifest_path),
        "tenderFileCount": len(tender_paths),
        "templateFileCount": 1 if template_path else 0,
        "hasAttachFile": bool(attach_path),
        "directoryTemplateCount": len(directory_templates),
        "directoryTemplateIds": [str(item.get("id") or "") for item in directory_templates],
    }


def _copy_tender_inputs(file_records: list[dict[str, Any]], work_dir: Path) -> list[Path]:
    copied: list[Path] = []
    for index, record in enumerate(file_records, start=1):
        source = Path(str(record.get("path") or "")).expanduser()
        if not source.exists() or source.suffix.lower() != ".docx":
            continue
        name = _safe_file_name(str(record.get("name") or source.name), f"招标文件-{index}.docx")
        if "招标" not in name:
            name = f"招标文件-{index}{source.suffix.lower() or '.docx'}"
        destination = _unique_path(work_dir / name)
        shutil.copy2(source, destination)
        copied.append(destination)
    return copied


def _copy_template_inputs(file_records: list[dict[str, Any]], work_dir: Path) -> tuple[Path | None, Path | None]:
    docx_records = [
        record
        for record in file_records
        if Path(str(record.get("path") or "")).expanduser().exists()
        and Path(str(record.get("path") or "")).suffix.lower() == ".docx"
    ]
    attach_record = next(
        (
            record
            for record in docx_records
            if "附表" in str(record.get("name") or Path(str(record.get("path") or "")).name)
        ),
        None,
    )
    template_record = next(
        (
            record
            for record in docx_records
            if record is not attach_record
            and "附表" not in str(record.get("name") or Path(str(record.get("path") or "")).name)
        ),
        None,
    )
    if template_record is None and docx_records:
        template_record = docx_records[0]

    template_path = (
        _copy_single_template(template_record, work_dir / "投标文件-正文.docx")
        if template_record is not None
        else None
    )
    attach_path = (
        _copy_single_template(attach_record, work_dir / "投标文件-附表.docx")
        if attach_record is not None and attach_record is not template_record
        else None
    )
    return template_path, attach_path


def _copy_single_template(record: dict[str, Any], destination: Path) -> Path:
    source = Path(str(record.get("path") or "")).expanduser()
    resolved_destination = destination.with_suffix(source.suffix.lower() or ".docx")
    shutil.copy2(source, resolved_destination)
    return resolved_destination


def _safe_file_name(value: str, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法为文件生成唯一路径：{path}")


def _normalize_bid_type(value: str) -> str:
    return value if value in {"技术标", "商务标"} else "技术标"


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
    skill_workspace: dict[str, Any],
) -> str:
    tender_hint_text = "\n".join(f"- {item}" for item in tender_hints) or "- 无明显章节线索"
    template_hint_text = "\n".join(f"- {item}" for item in template_hints) or "- 当前没有模板章节线索"
    include_key_points_text = "是" if include_key_points else "否"
    project_identity_text = json.dumps(skill_workspace.get("projectIdentity") or {}, ensure_ascii=False)
    directory_template_text = _format_directory_templates_for_prompt(
        skill_workspace.get("directoryTemplates") or []
    )

    return f"""
Use the {TOC_SKILL_NAME} skill.

你现在在做 {skill_workspace["bidType"]} 的 S2 目录生成，请调用 OpenCode skill 读取招标文件、投标正文模板、可选附表模板和素材 Wiki，输出一个可直接给后端解析的目录 JSON。

项目名称：{project_name}
目录策略：{outline_strategy}
是否尽量包含关键评分点：{include_key_points_text}
工作目录：{skill_workspace["workDir"]}
manifest：{skill_workspace["manifestPath"]}
manifest 备份：{skill_workspace["canonicalManifestPath"]}
后端 API：{skill_workspace["apiBaseUrl"]}
输出文件：{skill_workspace["outputFile"]}
项目身份：{project_identity_text}

目录模板沉淀：
{directory_template_text}

请先按投标模板目录起基础目录，再对照招标要求删改、补改，并结合 {skill_workspace["bidType"]} Wiki 素材库给出新增/删除/适配建议。读取 Wiki 时必须按项目身份过滤：通用素材可读；客户素材需 customer_id/同义词命中；项目素材需 project_id/project_code 命中。
如果 manifest 中包含 directoryTemplates，请把这些通用/客户目录模板作为 S2 目录生成和 S3 审核的对照结构；项目上传的投标模板仍为主骨架，目录模板沉淀只补齐缺失的稳定章节或客户专属结构。

请直接调用一次 Bash 工具执行下面命令，Bash 工具 timeout 必须设置为 600000 毫秒或更高。不要先检查工作目录，不要先执行 pwd/ls/cat/read/glob，不要拆成多条命令，不要改写命令或路径。命令会把完整目录 JSON 写入 outputFile，并只在 stdout 打印小型摘要 JSON：

{TOC_SKILL_COMMAND} {skill_workspace["manifestPath"]}

只返回命令 stdout 中的小型 JSON，不要返回解释文字，不要使用 Markdown 代码块。
不要再使用 Read/Glob/Cat 打开完整 outputFile；完整目录 JSON 由后端根据 outputFile 自行读取。
返回格式必须是：
{{
  "schema_version": "bid-toc-json-v1",
  "document_title": "投标文件总目录",
  "outputFile": "{skill_workspace["outputFile"]}",
  "summary": {{"total_items": 0, "annotation_counts": {{}}}},
  "itemCount": 0
}}

规则：
1. 目录层级最多 6 层。
2. 标题要简洁，适合中文技术标目录。
3. 目录必须以投标模板目录为主骨架，再根据招标要求重命名、删除不适用章节、补充遗漏章节。
4. 不要编造公司业绩、参数或事实内容，这里只生成目录结构。
5. 如果 manifest 中的 wiki 目录为空，必须通过后端 API 导出当前 {skill_workspace["bidType"]} Wiki，再继续生成。

招标章节线索：
{tender_hint_text}

投标模板章节线索：
{template_hint_text}

招标正文摘录（仅前段关键信息）：
{tender_excerpt}
""".strip()


def _format_directory_templates_for_prompt(directory_templates: list[dict[str, Any]]) -> str:
    if not directory_templates:
        return "- 未命中目录模板沉淀"
    compact_profiles: list[dict[str, Any]] = []
    for profile in directory_templates:
        chapters = []
        for chapter in profile.get("chapters") or []:
            chapters.append(
                {
                    "num": chapter.get("num") or "",
                    "title": chapter.get("title") or "",
                    "h2s": [
                        {
                            "num": h2.get("num") or "",
                            "title": h2.get("title") or "",
                        }
                        for h2 in (chapter.get("h2s") or [])
                    ],
                }
            )
        compact_profiles.append(
            {
                "id": profile.get("id") or "",
                "name": profile.get("name") or "",
                "source": profile.get("source") or "",
                "chapters": chapters,
            }
        )
    return json.dumps(compact_profiles, ensure_ascii=False, indent=2)


def _nodes_from_generation_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(result.get("items"), list):
        return _nodes_from_toc_items(result["items"])
    return _normalize_nodes(result["nodes"])


def _resolve_toc_generation_result(
    result: dict[str, Any],
    skill_workspace: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(result.get("items"), list) or isinstance(result.get("nodes"), list):
        return result

    output_file = Path(str(result.get("outputFile") or skill_workspace.get("outputFile") or ""))
    if output_file.exists():
        loaded = json.loads(output_file.read_text(encoding="utf-8"))
        if isinstance(loaded, dict) and isinstance(loaded.get("items"), list):
            loaded["outputFile"] = str(output_file)
            return loaded
    raise RuntimeError("futurecode 已返回目录摘要，但后端未能读取完整目录 JSON。")


def _summary_from_generation_result(result: dict[str, Any]) -> str:
    summary = result.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    if isinstance(summary, dict):
        total_items = summary.get("total_items")
        annotation_counts = summary.get("annotation_counts") or {}
        if isinstance(annotation_counts, dict) and annotation_counts:
            counts = "，".join(
                f"{key}{value}"
                for key, value in annotation_counts.items()
                if value
            )
            if counts:
                return f"目录生成完成，共 {total_items or 0} 条目录项（{counts}）。"
        return f"目录生成完成，共 {total_items or 0} 条目录项。"
    return "目录生成完成。"


def _nodes_from_toc_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []
    stack: list[tuple[int, dict[str, Any]]] = []
    counters: list[int] = []

    for fallback_order, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        level = _coerce_toc_level(item.get("level"))
        if not stack and level > 1:
            level = 1
        elif stack and level > stack[-1][0] + 1:
            level = stack[-1][0] + 1

        while stack and stack[-1][0] >= level:
            stack.pop()

        counters = counters[:level]
        if len(counters) < level:
            counters.extend([0] * (level - len(counters)))
        counters[level - 1] += 1
        node_id = "OL-" + "-".join(str(part) for part in counters[:level] if part)

        title = _toc_item_title(item, fallback_order)
        node = {
            "id": node_id,
            "title": title,
            "children": [],
            "tocNumber": str(item.get("number") or "").strip(),
            "annotation": str(item.get("annotation") or "").strip(),
            "source": str(item.get("source") or "").strip(),
            "reason": str(item.get("reason") or "").strip(),
        }
        if isinstance(item.get("source_refs"), list):
            node["sourceRefs"] = item["source_refs"]
        if isinstance(item.get("material_refs"), list):
            node["materialRefs"] = item["material_refs"]
        if stack:
            stack[-1][1].setdefault("children", []).append(node)
        else:
            roots.append(node)
        stack.append((level, node))

    return roots


def _coerce_toc_level(value: Any) -> int:
    try:
        level = int(value)
    except (TypeError, ValueError):
        level = 1
    return max(1, min(level, 6))


def _toc_item_title(item: dict[str, Any], fallback_order: int) -> str:
    title = str(item.get("title") or "").strip()
    number = str(item.get("number") or "").strip()
    if title:
        if number and not re.fullmatch(r"\d+(?:\.\d+)*", number):
            return f"{number} {title}".strip()
        return title
    if number:
        return number
    return f"未命名章节{fallback_order}"


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
