#!/usr/bin/env python3
"""按技术标三级目录 JSON 索引（`technical_material_index.json`）一一镜像，
构建技术标素材 Wiki blueprint。

Wiki 结构与素材库真实层级一一对应：

    root（技术标Wiki）
      └─ 一级节点 = tier        （标准文件 / 客户定制 / 项目定制）
           └─ 二级节点 = 3 级目录 （机型号 / 客户名 / 项目标识）
                └─ 深层子目录…… （按文件完整 path 还原素材库原始层级）
                     └─ 文件卡片 （每个 file 一张卡片）

索引本身归并到 3 级目录，但每个 file 的 `path` 保留完整原始路径，
本脚本据此在 3 级目录内重建 4 级及更深的子目录节点，与素材库结构对齐。

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
    return str(value or "").replace("\n", " ").replace("|", "\\|").strip()


def render_preview_block(preview: dict[str, Any]) -> list[str]:
    lead = md_inline(preview.get("lead"))
    points = [md_inline(item) for item in (preview.get("points") or []) if str(item).strip()]
    key_params = [item for item in (preview.get("keyParams") or []) if isinstance(item, dict)]
    hints = [md_inline(item) for item in (preview.get("retrievalHints") or []) if str(item).strip()]
    if not lead and not points and not key_params and not hints:
        return []

    source = str(preview.get("source") or "").strip()
    source_label = "本地 TLDR" if source == "local" else "AI 生成"
    lines: list[str] = ["## TLDR 文件信息卡片", "", f"> 来源：{source_label}", ""]
    if lead:
        lines += [f"> {lead}", ""]
    if points:
        lines += ["### 核心要点", ""]
        lines += [f"- {point}" for point in points[:6]]
        lines.append("")
    if key_params:
        lines += ["### 关键参数", "", "| 参数 | 值 |", "|---|---|"]
        for item in key_params[:8]:
            lines.append(f"| {md_escape(item.get('label'))} | {md_escape(item.get('value'))} |")
        lines.append("")
    if hints:
        lines += ["### 检索提示", ""]
        lines += [f"- {hint}" for hint in hints[:6]]
        lines.append("")
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

    lines = [f"# {name}", ""]
    preview = file.get("preview") if isinstance(file.get("preview"), dict) else {}
    preview_lines = render_preview_block(preview) if preview else []
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
    if not preview_lines:
        lines.append("> 本卡片仅为三级目录结构索引，不承载文件正文。")
    lines.append("> 卡片在 Wiki 中的层级与素材库原始目录一一对应，完整路径见上方文件定位。")

    tags = [BID_TYPE, "文件卡片", TIER_LABELS.get(tier_code, tier_code)]
    if preview:
        tags.append("内容预览")
    if ext:
        tags.append(ext)
    return node(name, "\n".join(lines) + "\n", tags=tags)


def file_subdir_segments(file: dict[str, Any], folder_path: str) -> list[str]:
    """文件相对 3 级目录的中间子目录段（不含文件名）。

    索引把深层文件归并进 3 级目录节点，但 `path` 保留完整原始路径，
    据此可还原 4 级及更深的真实层级。路径不在该目录下时视为直属文件。
    """
    full_path = str(file.get("path") or "").strip("/")
    prefix = str(folder_path or "").strip("/")
    if not prefix or not full_path.startswith(prefix + "/"):
        return []
    parts = [part for part in full_path[len(prefix) + 1 :].split("/") if part]
    return parts[:-1]


def build_subdir_node(
    name: str,
    dir_path: str,
    entries: list[tuple[list[str], dict[str, Any]]],
    tier_code: str,
    folder: dict[str, Any],
) -> dict[str, Any]:
    """深层子目录节点：还原素材库 4 级及更深的真实目录层级。"""
    direct_files: list[dict[str, Any]] = []
    by_subdir: dict[str, list[tuple[list[str], dict[str, Any]]]] = {}
    for segments, file in entries:
        if not segments:
            direct_files.append(file)
        else:
            by_subdir.setdefault(segments[0], []).append((segments[1:], file))

    children = [
        build_subdir_node(sub_name, f"{dir_path}/{sub_name}", sub_entries, tier_code, folder)
        for sub_name, sub_entries in by_subdir.items()
    ]
    children.extend(build_file_card(f, tier_code, folder) for f in direct_files)

    lines = [
        f"# {name}",
        "",
        f"- 目录路径: `{dir_path}`",
        f"- 档位: {TIER_LABELS.get(tier_code, tier_code)} ({tier_code})",
        f"- 直属文件数: {len(direct_files)}",
        f"- 子目录数: {len(by_subdir)}",
        "",
        "## 直属文件清单",
        "",
        "| material_id | 文件名 | 扩展名 | 清洗状态 |",
        "|---|---|---|---|",
    ]
    if not direct_files:
        lines.append("| - | （该目录暂无直属文件） | - | - |")
    for f in direct_files:
        lines.append(
            "| {fid} | {name} | {ext} | {status} |".format(
                fid=md_escape(f.get("id")),
                name=md_escape(f.get("name")),
                ext=md_escape(f.get("ext")),
                status=md_escape(clean_status_label(f.get("cleanStatus"))),
            )
        )
    lines.append("")
    lines.append("> 本节点按素材库原始目录层级自动生成。")

    tags = [BID_TYPE, "子目录", TIER_LABELS.get(tier_code, tier_code)]
    return node(name, "\n".join(lines) + "\n", tags=tags, children=children)


def build_folder_children(folder: dict[str, Any], tier_code: str) -> list[dict[str, Any]]:
    """3 级目录的子节点：先按文件完整 path 还原深层子目录，再挂直属文件卡片。"""
    folder_path = str(folder.get("path") or "")
    files = [f for f in (folder.get("files") or []) if isinstance(f, dict)]

    direct_files: list[dict[str, Any]] = []
    by_subdir: dict[str, list[tuple[list[str], dict[str, Any]]]] = {}
    for f in files:
        segments = file_subdir_segments(f, folder_path)
        if not segments:
            direct_files.append(f)
        else:
            by_subdir.setdefault(segments[0], []).append((segments[1:], f))

    children = [
        build_subdir_node(sub_name, f"{folder_path}/{sub_name}", sub_entries, tier_code, folder)
        for sub_name, sub_entries in by_subdir.items()
    ]
    children.extend(build_file_card(f, tier_code, folder) for f in direct_files)
    return children


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
            "## 文件清单（含深层子目录文件）",
            "",
            "| material_id | 文件名 | 相对路径 | 扩展名 | 清洗状态 |",
            "|---|---|---|---|---|",
        ]
    )
    if not files:
        lines.append("| - | （该目录暂无归并文件） | - | - | - |")
    for f in files:
        rel_dir = "/".join(file_subdir_segments(f, path)) or "—"
        lines.append(
            "| {fid} | {name} | {rel} | {ext} | {status} |".format(
                fid=md_escape(f.get("id")),
                name=md_escape(f.get("name")),
                rel=md_escape(rel_dir),
                ext=md_escape(f.get("ext")),
                status=md_escape(clean_status_label(f.get("cleanStatus"))),
            )
        )

    children = build_folder_children(folder, tier_code)
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
    return node(raw_name, "\n".join(lines) + "\n", tags=[BID_TYPE, label, "档位"], children=children)


def build_blueprint(manifest: dict[str, Any]) -> dict[str, Any]:
    index = extract_index(manifest)
    bid_type = str(index.get("bidType") or BID_TYPE)
    root_title = str(manifest.get("rootTitle") or f"{bid_type}Wiki（自动生成）")

    tiers = [t for t in (index.get("tiers") or []) if isinstance(t, dict)]

    stats = index.get("stats") if isinstance(index.get("stats"), dict) else {}
    nodes = [build_tier_node(t) for t in tiers]

    folder_total = sum(len(t.get("folders") or []) for t in tiers)
    summary = (
        f"已按三级目录 JSON 索引重建 {bid_type} Wiki："
        f"{len(tiers)} 个档位 / {folder_total} 个 3 级目录 / "
        f"{stats.get('fileCount', '?')} 个文件，深层子目录已按文件完整路径还原，与素材库层级一致。"
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
