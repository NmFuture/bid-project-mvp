from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.services.material_store import material_store
from app.services.opencode_client import OpencodeClient

DEFAULT_REFERENCE_WIKI_PATH = Path(
    "/Users/anbocheng/Desktop/20260412_技术标/20260413_技术标_组织优化/素材库-20260413-wlb-clean-wiki/wiki"
)
MAX_EXCERPT_CHARS = 5000


def _read_excerpt(path: Path, limit: int = MAX_EXCERPT_CHARS) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8").strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}\n..."


def _summarize_reference_wiki(reference_root: Path) -> dict[str, Any]:
    card_root = reference_root / "卡片"
    common_dirs = []
    custom_dirs = []
    if card_root.exists():
        common_root = card_root / "通用"
        custom_root = card_root / "定制"
        if common_root.exists():
            common_dirs = sorted([item.name for item in common_root.iterdir() if item.is_dir()])
        if custom_root.exists():
            custom_dirs = sorted([item.name for item in custom_root.iterdir() if item.is_dir()])

    return {
        "referenceRoot": str(reference_root),
        "hasReference": reference_root.exists(),
        "indexExcerpt": _read_excerpt(reference_root / "index.md"),
        "rulesExcerpt": _read_excerpt(reference_root / "rules.md"),
        "synonymsExcerpt": _read_excerpt(reference_root / "synonyms.md"),
        "skeletonExcerpt": _read_excerpt(reference_root / "skeleton.md"),
        "commonCardGroups": common_dirs,
        "customCardGroups": custom_dirs,
    }


def _build_wiki_generation_prompt(reference: dict[str, Any]) -> str:
    payload = json.dumps(reference, ensure_ascii=False, indent=2)
    return f"""
Use the bid-wiki-bootstrap-json skill.

目标：
基于参考 wiki，生成一份“平台级 Wiki = 标书装配规则库”的初始化蓝图。

业务要求：
1. 平台级 Wiki 要体现“卡片装配系统”，不是知识百科。
2. 必须把结构拆成两层概念：
   - 平台级 Wiki：通用卡片、章节骨架、规则、同义词、挂载说明
   - 项目级 Wiki：只作为模板/约定进行说明，不生成项目实例数据
3. 结果要适合落入当前系统的 wiki tree，每个节点都可以有 markdown 内容。
4. 内容要尽量继承参考 wiki 的组织方式，尤其是：
   - index = 卡片目录
   - rules = 装配规则
   - synonyms = 检索映射
   - skeleton_section = 章节归属
5. 不要生成过深的细枝末节，控制为“可直接导入系统的 starter wiki”。

输出要求：
1. 只输出 JSON，不要解释，不要 Markdown 代码块。
2. JSON 结构必须为：
{{
  "summary": "一句简短总结",
  "rootTitle": "平台级Wiki（自动生成）",
  "nodes": [
    {{
      "title": "节点标题",
      "markdownContent": "# 标题\\n\\n正文",
      "tags": ["通用材料"],
      "applicableTypes": ["通用"],
      "children": []
    }}
  ]
}}
3. 顶层建议至少包含这些分组：
   - 平台级Wiki说明
   - 章节骨架
   - 装配规则
   - 同义词映射
   - 通用卡片
   - 项目级Wiki模板
4. “通用卡片”下按参考 wiki 的主要目录分组输出。
5. “项目级Wiki模板”要明确说明 override / append / reference 三种补料方式。

参考 wiki 摘要：
{payload}
""".strip()


def _fallback_wiki_blueprint(reference: dict[str, Any]) -> dict[str, Any]:
    common_sections = reference.get("commonCardGroups") or [
        "标前概述",
        "总体方案",
        "专项技术",
        "风资源评估",
        "技术标准",
    ]
    custom_sections = reference.get("customCardGroups") or ["项目数据"]
    custom_sections_text = "\n- ".join(custom_sections)
    common_children = [
        {
            "title": section,
            "markdownContent": f"# {section}\n\n这是平台级通用卡片分组，用于沉淀标准专题卡与章节挂载方式。",
            "tags": ["通用材料"],
            "applicableTypes": ["通用"],
            "children": [],
        }
        for section in common_sections
    ]
    return {
        "summary": "已按参考 wiki 的组织方式生成平台级 Wiki 起始结构。",
        "rootTitle": "平台级Wiki（自动生成）",
        "nodes": [
            {
                "title": "平台级Wiki说明",
                "markdownContent": "# 平台级Wiki说明\n\n平台级 Wiki 是标书装配规则库，用于在 S1 前提供专题卡、规则、同义词和骨架映射。",
                "tags": ["通用材料"],
                "applicableTypes": ["通用"],
                "children": [],
            },
            {
                "title": "章节骨架",
                "markdownContent": "# 章节骨架\n\n用来维护技术标/商务标的骨架章节，以及卡片与章节的 skeleton_section 映射。",
                "tags": ["技术标", "商务标"],
                "applicableTypes": ["技术标", "商务标", "通用"],
                "children": [],
            },
            {
                "title": "装配规则",
                "markdownContent": "# 装配规则\n\n维护必选、条件触发、覆盖、叠加、fallback 等装配逻辑。",
                "tags": ["通用材料"],
                "applicableTypes": ["通用"],
                "children": [],
            },
            {
                "title": "同义词映射",
                "markdownContent": "# 同义词映射\n\n维护章节关键词到素材关键词的匹配关系，用于目录匹配和缺口识别。",
                "tags": ["通用材料"],
                "applicableTypes": ["通用"],
                "children": [],
            },
            {
                "title": "通用卡片",
                "markdownContent": "# 通用卡片\n\n按专题组织平台级标准卡片。",
                "tags": ["通用材料"],
                "applicableTypes": ["通用"],
                "children": common_children,
            },
            {
                "title": "项目级Wiki模板",
                "markdownContent": (
                    "# 项目级Wiki模板\n\n"
                    "项目级 Wiki 用于 S4-S6 阶段补充 case-specific 内容。\n\n"
                    "## 补料方式\n"
                    "- override：项目版覆盖平台版\n"
                    "- append：在平台版后附加项目说明\n"
                    "- reference：只挂证据和附件，不改正文\n\n"
                    f"## 推荐目录\n- {custom_sections_text}"
                ),
                "tags": ["通用材料"],
                "applicableTypes": ["技术标", "商务标", "通用"],
                "children": [],
            },
        ],
    }


def _parse_json_payload(content: str) -> dict[str, Any]:
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


def _normalize_blueprint_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(node.get("title") or "未命名节点"),
        "markdownContent": str(node.get("markdownContent") or f"# {str(node.get('title') or '未命名节点')}\n"),
        "tags": [str(item) for item in (node.get("tags") or []) if str(item).strip()],
        "applicableTypes": [str(item) for item in (node.get("applicableTypes") or []) if str(item).strip()] or ["通用"],
        "children": [_normalize_blueprint_node(item) for item in (node.get("children") or []) if isinstance(item, dict)],
    }


def _normalize_blueprint(payload: dict[str, Any]) -> dict[str, Any]:
    nodes = payload.get("nodes") or []
    if not isinstance(nodes, list):
        raise RuntimeError("Wiki 蓝图格式错误：nodes 必须为数组。")
    return {
        "summary": str(payload.get("summary") or "平台级 Wiki 已生成。"),
        "rootTitle": str(payload.get("rootTitle") or "平台级Wiki（自动生成）"),
        "nodes": [_normalize_blueprint_node(item) for item in nodes if isinstance(item, dict)],
    }


async def generate_platform_wiki(reference_path: str = "", mode: str = "create") -> dict[str, Any]:
    reference_root = Path(reference_path).expanduser().resolve() if reference_path else DEFAULT_REFERENCE_WIKI_PATH
    reference = _summarize_reference_wiki(reference_root)
    prompt = _build_wiki_generation_prompt(reference)
    opencode_output: dict[str, Any] = {"status": "skipped", "parts": []}

    try:
        client = OpencodeClient()
        session = client.create_session("平台 Wiki 生成")
        response = client.send_prompt(str(session.get("id") or ""), prompt)
        blueprint = _normalize_blueprint(_parse_json_payload("\n".join(
            str(part.get("text") or "")
            for part in response.get("parts") or []
            if part.get("type") == "text"
        )))
        opencode_output = client._build_output_trace(str(session.get("id") or ""), response)
    except Exception as exc:
        blueprint = _fallback_wiki_blueprint(reference)
        opencode_output = {
            "status": "failed",
            "parts": [{"type": "text", "text": f"平台 Wiki 生成失败，已回退为默认结构：{exc}"}],
        }

    imported = await material_store.import_generated_wiki_blueprint(
        root_title=blueprint["rootTitle"],
        nodes=blueprint["nodes"],
        mode=mode,
    )
    imported["generation"] = {
        "summary": blueprint["summary"],
        "referencePath": str(reference_root),
        "opencodeOutput": opencode_output,
    }
    return imported
