"""Wiki blueprint 公共工具。

技术标与商务标两条 Wiki 生成线都用到的最小纯工具集（JSON 解析、blueprint
归一、本地 skill 脚本执行、时间戳）。这里只放与标种无关的通用逻辑，不放任何
按 bid_type 分流或业务（素材清单 / LLM 精修）代码——分流由各自的生成模块直接
调用自己的 store 完成。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from app.core.config import settings


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_json_payload(content: str) -> dict[str, Any]:
    cleaned = str(content or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise RuntimeError("opencode 返回内容里没有可解析的 JSON。")
        return json.loads(cleaned[start : end + 1])


def normalize_blueprint_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(node.get("title") or "未命名节点"),
        "markdownContent": str(node.get("markdownContent") or f"# {str(node.get('title') or '未命名节点')}\n"),
        "tags": [str(item) for item in (node.get("tags") or []) if str(item).strip()],
        "applicableTypes": [str(item) for item in (node.get("applicableTypes") or []) if str(item).strip()] or ["通用"],
        "children": [normalize_blueprint_node(item) for item in (node.get("children") or []) if isinstance(item, dict)],
    }


def normalize_blueprint(payload: dict[str, Any]) -> dict[str, Any]:
    nodes = payload.get("nodes") or []
    if not isinstance(nodes, list):
        raise RuntimeError("Wiki 蓝图格式错误：nodes 必须为数组。")
    return {
        "summary": str(payload.get("summary") or "平台级 Wiki 已生成。"),
        "rootTitle": str(payload.get("rootTitle") or "平台级Wiki（自动生成）"),
        "rootMarkdownContent": str(payload.get("rootMarkdownContent") or ""),
        "nodes": [normalize_blueprint_node(item) for item in nodes if isinstance(item, dict)],
    }


def load_wiki_blueprint_result(result: dict[str, Any]) -> dict[str, Any]:
    output_file = Path(str(result.get("outputFile") or "")).expanduser()
    if not output_file.exists() or not output_file.is_file():
        return result
    try:
        payload = json.loads(output_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Wiki Skill 生成的 outputFile 不是有效 JSON：{output_file}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("nodes"), list):
        raise RuntimeError(f"Wiki Skill 生成的 outputFile 缺少 nodes：{output_file}")
    if isinstance(result.get("opencodeOutput"), dict):
        payload["opencodeOutput"] = result["opencodeOutput"]
    return payload


def run_local_wiki_skill(manifest_path: Path, *, skill_name: str, runner: Path) -> dict[str, Any]:
    """确定性执行某个 wikibuild skill 的 run_from_manifest.py（subprocess，不走 LLM）。

    由调用方显式传入 skill_name 与 runner，因此本函数与 bid_type 完全解耦。
    """
    if not runner.exists():
        raise RuntimeError(f"Wiki Skill runner 不存在：{runner}")

    completed = subprocess.run(
        [sys.executable, str(runner), str(manifest_path)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=max(30, int(settings.opencode_timeout_sec)),
    )
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if completed.returncode != 0:
        detail = "\n".join(part for part in (stdout, stderr) if part)
        raise RuntimeError(f"Wiki Skill runner 执行失败（{completed.returncode}）：{detail}")

    try:
        result = json.loads(stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Wiki Skill runner 返回内容不是有效 JSON：{stdout}") from exc

    result.setdefault("schema_version", "bid-wiki-blueprint-v1")
    result["opencodeOutput"] = {
        "status": "received",
        "sessionId": str(manifest_path),
        "providerId": "local-skill",
        "modelId": skill_name,
        "receivedAt": now_iso(),
        "parts": [{"type": "text", "text": stdout}],
    }
    return result


# ---------------------------------------------------------------------------
# docx 结构解析原语
#
# 这组工具同时被商务标 Wiki 卡片生成（business_wiki_generation）和技术标三级目录
# 索引的预览解析（technical_material_index）复用，与标种无关，故放在公共模块，
# 避免技术标侧反向依赖商务标模块。
# ---------------------------------------------------------------------------

MAX_CARD_EXCERPT_PARAGRAPHS = 10
MAX_CARD_HEADINGS = 80
MAX_SYNC_DOCX_BYTES = 30 * 1024 * 1024
HEADING_STYLE_RE = re.compile(r"(?:Heading|标题)\s*([1-9])|Heading([1-9])", re.IGNORECASE)
NUMBERED_HEADING_RE = re.compile(
    r"^(?:(第[一二三四五六七八九十百]+[章节篇])|([一二三四五六七八九十]+[、.．])|((?:\d+[.．、]){1,5}))\s*\S+"
)
WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def clean_docx_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def xml_text(element: ET.Element) -> str:
    parts: list[str] = []
    for node in element.iter(f"{WORD_NS}t"):
        if node.text:
            parts.append(node.text)
    return clean_docx_text("".join(parts))


def xml_paragraph_style(element: ET.Element) -> str:
    p_style = element.find(f"./{WORD_NS}pPr/{WORD_NS}pStyle")
    if p_style is None:
        return ""
    return str(p_style.attrib.get(f"{WORD_NS}val") or p_style.attrib.get("val") or "")


def heading_level_from_explicit_style(style_id: str) -> int | None:
    style = str(style_id or "")
    match = HEADING_STYLE_RE.search(style)
    if match:
        return int(match.group(1) or match.group(2))
    if style in {"1", "2", "3", "4", "5", "6", "7", "8", "9"}:
        return int(style)
    return None


def heading_level_from_style(style_id: str, text: str) -> int | None:
    explicit_level = heading_level_from_explicit_style(style_id)
    if explicit_level is not None:
        return explicit_level
    numbered = NUMBERED_HEADING_RE.match(text)
    if not numbered:
        return None
    numeric = numbered.group(3)
    if numeric:
        return max(1, min(6, len(re.findall(r"\d+", numeric))))
    return 1


def extract_docx_profile(
    data: bytes,
    *,
    heading_limit: int | None = MAX_CARD_HEADINGS,
) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            document_xml = archive.read("word/document.xml")
    except Exception as exc:
        return {
            "headings": [],
            "bodyHeadings": [],
            "paragraphs": [],
            "tables": [],
            "tableCount": 0,
            "parseError": f"docx 读取失败：{exc}",
        }

    headings: list[dict[str, Any]] = []
    body_headings: list[dict[str, Any]] = []
    paragraphs: list[str] = []
    table_previews: list[str] = []
    seen_paragraphs: set[str] = set()
    table_count = 0
    table_depth = 0
    try:
        for event, element in ET.iterparse(BytesIO(document_xml), events=("start", "end")):
            if event == "start":
                if element.tag == f"{WORD_NS}tbl":
                    table_depth += 1
                continue
            if element.tag == f"{WORD_NS}p":
                text = xml_text(element)
                if text:
                    style_id = xml_paragraph_style(element)
                    explicit_level = heading_level_from_explicit_style(style_id)
                    level = explicit_level or heading_level_from_style(style_id, text)
                    if level is not None and (heading_limit is None or len(headings) < heading_limit):
                        heading = {"level": level, "title": text[:180]}
                        headings.append(heading)
                        if (
                            table_depth == 0
                            and explicit_level is not None
                            and (heading_limit is None or len(body_headings) < heading_limit)
                        ):
                            body_headings.append({"level": explicit_level, "title": text[:180]})
                    elif (
                        len(paragraphs) < MAX_CARD_EXCERPT_PARAGRAPHS
                        and len(text) >= 4
                        and text not in seen_paragraphs
                    ):
                        seen_paragraphs.add(text)
                        paragraphs.append(text[:260])
                element.clear()
            elif element.tag == f"{WORD_NS}tbl":
                table_count += 1
                if len(table_previews) < 6:
                    text = xml_text(element)
                    if text:
                        table_previews.append(text[:320])
                table_depth = max(0, table_depth - 1)
                element.clear()
            if (
                heading_limit is not None
                and len(headings) >= heading_limit
                and len(paragraphs) >= MAX_CARD_EXCERPT_PARAGRAPHS
                and len(table_previews) >= 6
            ):
                break
    except Exception as exc:
        return {
            "headings": headings,
            "bodyHeadings": body_headings,
            "paragraphs": paragraphs,
            "tables": table_previews,
            "tableCount": table_count,
            "parseError": f"docx XML 解析部分失败：{exc}",
        }

    return {
        "headings": headings if heading_limit is None else headings[:heading_limit],
        "bodyHeadings": body_headings if heading_limit is None else body_headings[:heading_limit],
        "paragraphs": paragraphs[:MAX_CARD_EXCERPT_PARAGRAPHS],
        "tables": table_previews,
        "tableCount": table_count,
        "parseError": "",
    }


def material_level_range(headings: list[dict[str, Any]]) -> str:
    levels = sorted({int(item.get("level") or 0) for item in headings if item.get("level")})
    if not levels:
        return "none"
    return f"L{levels[0]}-L{levels[-1]}"


def format_heading_tree(headings: list[dict[str, Any]], limit: int = 60) -> str:
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
