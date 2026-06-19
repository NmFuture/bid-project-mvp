#!/usr/bin/env python3
"""按技术标三级目录 JSON 索引（`technical_material_index.json`）一一镜像，
构建技术标素材 Wiki blueprint。

Wiki 结构与 JSON 一一对应：

    root（技术标Wiki）
      └─ 一级节点 = tier        （标准文件 / 客户定制 / 项目定制）
           └─ 二级节点 = 3 级目录 （机型号 / 客户名 / 项目标识）
                └─ 三级节点 = 文件卡片 （每个 file 一张卡片）

源 JSON 结构（schemaVersion = 1）详见
doc/anbc_doc/20260618-技术标三级目录JSON索引-下游使用Handoff.md。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


BID_TYPE = "技术标"

# tier -> 中文档位标签（与 JSON 的 tier.name / handoff 文档保持一致）
TIER_LABELS = {
    "standard": "标准文件",
    "customer": "客户定制",
    "project": "项目定制",
}

# 一级节点固定顺序：标准 → 客户 → 项目
TIER_ORDER = ["standard", "customer", "project"]

# 3 级目录名在每档下的语义（来自 handoff 文档第 4 节）
TIER_FOLDER_MEANING = {
    "standard": "机型号或分类",
    "customer": "客户名",
    "project": "项目标识",
}


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"输入必须是 JSON 对象：{path}")
    return data


def md_escape(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", "<br>")


def md_inline(value: Any) -> str:
    """单行内联文本：换行折成空格，转义表格分隔符。用于预览区导读/要点/提示。"""
    return str(value or "").replace("\n", " ").replace("|", "\\|").strip()


def render_preview_block(preview: dict[str, Any]) -> list[str]:
    """把 file entry 的 AI 预览子对象渲染成 Markdown 区块；无有效内容返回 []。"""
    lead = md_inline(preview.get("lead"))
    points = [md_inline(p) for p in (preview.get("points") or []) if str(p).strip()]
    if not lead and not points:
        return []

    lines: list[str] = ["## 内容预览（AI 生成）", ""]
    if lead:
        lines += [f"> {lead}", ""]
    if points:
        lines.append("**要点**")
        lines += [f"- {p}" for p in points[:5]]
        lines.append("")

    params = [kv for kv in (preview.get("keyParams") or []) if isinstance(kv, dict)]
    params = [kv for kv in params if str(kv.get("label") or "").strip() or str(kv.get("value") or "").strip()]
    if params:
        lines += ["**关键参数**", "", "| 参数 | 值 |", "|---|---|"]
        lines += [
            f"| {md_escape(kv.get('label'))} | {md_escape(kv.get('value'))} |"
            for kv in params[:8]
        ]
        lines.append("")

    hints = [md_inline(h) for h in (preview.get("retrievalHints") or []) if str(h).strip()]
    if hints:
        lines += ["**检索提示**: " + " · ".join(hints[:6]), ""]

    lines += ["---", ""]
    return lines


def extract_index(manifest: dict[str, Any]) -> dict[str, Any]:
    """从传入的数据中定位三级目录索引负载。

    既接受原始 index JSON（顶层带 ``tiers``），也接受将其嵌在
    ``materialIndex`` / ``technicalMaterialIndex`` 键下的 manifest 包裹。
    """
    if isinstance(manifest.get("tiers"), list):
        return manifest
    for key in ("materialIndex", "technicalMaterialIndex", "index"):
        candidate = manifest.get(key)
        if isinstance(candidate, dict) and isinstance(candidate.get("tiers"), list):
            return candidate
    # 空 / 无法识别时按空索引处理，让调用方仍能拿到结构合法（虽空）的 blueprint。
    return {"bidType": BID_TYPE, "tiers": []}


def tier_label(tier: dict[str, Any]) -> str:
    code = str(tier.get("tier") or "").strip()
    return TIER_LABELS.get(code) or str(tier.get("name") or code or "未知档位")


def folder_identity(folder: dict[str, Any], tier_code: str) -> str:
    if tier_code == "customer":
        return str(folder.get("customerName") or "")
    if tier_code == "project":
        return str(folder.get("projectId") or "")
    return ""


def clean_status_label(status: str) -> str:
    return {
        "cleaned": "已清洗",
        "pending": "待清洗",
        "original_only": "仅原稿",
        "failed": "清洗失败",
    }.get(str(status or "").strip(), str(status or "未知"))


def node(
    title: str,
    markdown: str,
    *,
    tags: list[str] | None = None,
    children: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "markdownContent": markdown,
        "tags": tags or [BID_TYPE],
        "applicableTypes": [BID_TYPE],
        "children": children or [],
    }


def build_file_card(file: dict[str, Any], tier_code: str, folder: dict[str, Any]) -> dict[str, Any]:
    file_id = str(file.get("id") or "")
    name = str(file.get("name") or file_id or "未命名文件")
    path = str(file.get("path") or "")
    ext = str(file.get("ext") or "")
    status = str(file.get("cleanStatus") or "")
    preview = file.get("preview") if isinstance(file.get("preview"), dict) else None

    lines = [f"# {name}", ""]

    # AI 内容预览（若有）置于卡片顶部；缺失则降级为原纯目录索引卡片。
    preview_lines = render_preview_block(preview) if preview else []
    has_preview = bool(preview_lines)
    lines.extend(preview_lines)

    lines.extend([
        "## 文件定位",
        f"- material_id: {file_id}",
        f"- 完整路径: `{path}`",
        f"- 扩展名: {ext}",
        f"- 清洗状态: {clean_status_label(status)} ({status})",
        "",
        "## 所属档位",
        f"- tier: {tier_code} ({TIER_LABELS.get(tier_code, '')})",
        f"- 3 级目录: {folder.get('name') or ''}",
    ])
    identity = folder_identity(folder, tier_code)
    if tier_code == "customer":
        lines.append(f"- customer_name: {identity}")
    elif tier_code == "project":
        lines.append(f"- project_id: {identity}")
    lines.append("")
    lines.append("> 本卡片仅为三级目录结构索引，不承载文件正文。")
    lines.append("> 深层（4 级及更深）文件已归并到此 3 级目录下，原始层级见上方完整路径。")

    tags = [BID_TYPE, "文件卡片", TIER_LABELS.get(tier_code, tier_code)]
    if ext:
        tags.append(ext)
    if has_preview:
        tags.append("AI预览")
    return node(name, "\n".join(lines) + "\n", tags=tags)


def build_folder_node(folder: dict[str, Any], tier_code: str) -> dict[str, Any]:
    name = str(folder.get("name") or "未命名目录")
    path = str(folder.get("path") or "")
    identity = folder_identity(folder, tier_code)
    files = [f for f in (folder.get("files") or []) if isinstance(f, dict)]

    lines = [
        f"# {name}",
        "",
        f"- 目录路径: `{path}`",
        f"- 档位: {TIER_LABELS.get(tier_code, tier_code)} ({tier_code})",
        f"- 目录语义: {TIER_FOLDER_MEANING.get(tier_code, '')}",
    ]
    if tier_code == "customer":
        lines.append(f"- 客户名 (customerName): {identity or '（空）'}")
    elif tier_code == "project":
        lines.append(f"- 项目标识 (projectId): {identity or '（空）'}")
    lines.extend(
        [
            f"- 文件数 (fileCount): {folder.get('fileCount', len(files))}",
            f"- 更新时间 (updatedAt): {folder.get('updatedAt') or ''}",
            "",
            "## 文件清单",
            "",
            "| material_id | 文件名 | 扩展名 | 清洗状态 |",
            "|---|---|---|---|",
        ]
    )
    if not files:
        lines.append("| - | （该目录暂无归并文件） | - | - |")
    for f in files:
        lines.append(
            "| {fid} | {name} | {ext} | {status} |".format(
                fid=md_escape(f.get("id")),
                name=md_escape(f.get("name")),
                ext=md_escape(f.get("ext")),
                status=md_escape(clean_status_label(f.get("cleanStatus"))),
            )
        )

    children = [build_file_card(f, tier_code, folder) for f in files]
    tags = [BID_TYPE, "三级目录", TIER_LABELS.get(tier_code, tier_code)]
    if identity:
        tags.append(identity)
    return node(name, "\n".join(lines) + "\n", tags=tags, children=children)


def build_tier_node(tier: dict[str, Any]) -> dict[str, Any]:
    tier_code = str(tier.get("tier") or "").strip()
    label = tier_label(tier)
    raw_name = str(tier.get("name") or label)
    path = str(tier.get("path") or "")
    folders = [f for f in (tier.get("folders") or []) if isinstance(f, dict)]

    lines = [
        f"# {label}",
        "",
        f"- 档位代码 (tier): {tier_code}",
        f"- 2 级目录真实名 (name): {raw_name}",
        f"- 路径 (path): `{path}`",
        f"- 文件总数 (fileCount): {tier.get('fileCount', 0)}",
        f"- 3 级目录数: {len(folders)}",
        f"- 3 级目录语义: {TIER_FOLDER_MEANING.get(tier_code, '')}",
        "",
        "## 本档 3 级目录",
        "",
        "| 3 级目录 | 身份 | 文件数 |",
        "|---|---|---|",
    ]
    if not folders:
        lines.append("| （暂无 3 级目录） | - | - |")
    for f in folders:
        ident = folder_identity(f, tier_code)
        lines.append(
            "| {name} | {ident} | {count} |".format(
                name=md_escape(f.get("name")),
                ident=md_escape(ident or "—"),
                count=md_escape(f.get("fileCount", 0)),
            )
        )

    children = [build_folder_node(f, tier_code) for f in folders]
    # 一级节点标题带序号，固定顺序便于下游/人工浏览
    order_index = TIER_ORDER.index(tier_code) + 1 if tier_code in TIER_ORDER else 9
    title = f"{order_index:02d}-{label}"
    return node(title, "\n".join(lines) + "\n", tags=[BID_TYPE, label, "档位"], children=children)


def build_blueprint(manifest: dict[str, Any]) -> dict[str, Any]:
    index = extract_index(manifest)
    bid_type = str(index.get("bidType") or BID_TYPE)
    root_title = str(manifest.get("rootTitle") or f"{bid_type}Wiki（自动生成）")

    tiers = [t for t in (index.get("tiers") or []) if isinstance(t, dict)]
    # 固定 标准 → 客户 → 项目 顺序，未知 tier 排末尾
    tiers.sort(key=lambda t: TIER_ORDER.index(str(t.get("tier") or "")) if str(t.get("tier") or "") in TIER_ORDER else 99)

    stats = index.get("stats") if isinstance(index.get("stats"), dict) else {}
    nodes = [build_tier_node(t) for t in tiers]

    folder_total = sum(len(t.get("folders") or []) for t in tiers)
    summary = (
        f"已按三级目录 JSON 索引重建 {bid_type} Wiki："
        f"{len(tiers)} 个档位 / {folder_total} 个 3 级目录 / "
        f"{stats.get('fileCount', '?')} 个文件，结构 tier→folder→file 镜像 JSON。"
    )
    return {
        "summary": summary,
        "rootTitle": root_title,
        "nodes": nodes,
    }


def run_manifest(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    work_dir = Path(str(manifest.get("workDir") or manifest_path.parent)).expanduser()
    work_dir.mkdir(parents=True, exist_ok=True)
    output_file = Path(str(manifest.get("outputFile") or work_dir / "wiki_blueprint.json")).expanduser()
    output_file.parent.mkdir(parents=True, exist_ok=True)

    blueprint = build_blueprint(manifest)
    output_file.write_text(json.dumps(blueprint, ensure_ascii=False, indent=2), encoding="utf-8")

    index = extract_index(manifest)
    tiers = [t for t in (index.get("tiers") or []) if isinstance(t, dict)]
    return {
        "schema_version": "bid-wiki-blueprint-v2",
        "skill": "bid-tech-wiki-material-builder",
        "outputFile": str(output_file),
        "summary": blueprint["summary"],
        "rootTitle": blueprint["rootTitle"],
        "tierCount": len(tiers),
        "folderCount": sum(len(t.get("folders") or []) for t in tiers),
        "fileCount": (index.get("stats") or {}).get("fileCount") if isinstance(index.get("stats"), dict) else None,
        "nodeTitles": [str(n.get("title") or "") for n in blueprint.get("nodes") or []],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="根据技术标三级目录素材索引 JSON 构建技术标 Wiki blueprint。"
    )
    parser.add_argument("manifest", type=Path, help="technical_material_index.json 路径，或包裹它的 manifest 路径")
    args = parser.parse_args()
    response = run_manifest(load_json(args.manifest), args.manifest)
    print(json.dumps(response, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
