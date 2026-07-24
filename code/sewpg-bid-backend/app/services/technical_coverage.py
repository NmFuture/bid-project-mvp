from __future__ import annotations

import copy
from typing import Any


def build_technical_coverage(project: dict[str, Any]) -> dict[str, Any]:
    assembly_coverage = (project.get("fill_state") or {}).get("coverage")
    if isinstance(assembly_coverage, dict) and assembly_coverage:
        return copy.deepcopy(assembly_coverage)

    outline_nodes = list((project.get("outline_state") or {}).get("nodes") or [])
    if not outline_nodes:
        return {
            "percentage": 100,
            "fullCover": 0,
            "partialCover": 0,
            "noCover": 0,
            "tree": [],
            "partialItems": [],
            "noCoverItems": [],
        }

    sections = list((project.get("fill_state") or {}).get("sections") or [])
    section_status_map = {
        str(section.get("nodeId") or "").strip(): technical_coverage_status_from_generation_mode(
            section.get("generationMode")
        )
        for section in sections
        if str(section.get("nodeId") or "").strip()
    }

    tree = build_technical_coverage_tree(outline_nodes, section_status_map)
    partial_items, no_cover_items = build_technical_coverage_issue_lists(tree)
    full_cover, partial_cover, no_cover = summarize_technical_coverage_tree(tree)
    total = full_cover + partial_cover + no_cover
    percentage = 100 if total == 0 else round(((full_cover * 1.0) + (partial_cover * 0.5)) / total * 100)
    return {
        "percentage": percentage,
        "fullCover": full_cover,
        "partialCover": partial_cover,
        "noCover": no_cover,
        "tree": tree,
        "partialItems": partial_items,
        "noCoverItems": no_cover_items,
    }


def technical_coverage_status_from_generation_mode(mode: Any) -> str:
    mode_text = str(mode or "").strip()
    if mode_text == "generated":
        return "full"
    if mode_text == "generated_with_placeholder":
        return "partial"
    return "none"


def build_technical_coverage_tree(
    nodes: list[dict[str, Any]],
    section_status_map: dict[str, str],
    inherited_status: str | None = None,
) -> list[dict[str, Any]]:
    tree: list[dict[str, Any]] = []
    for node in nodes:
        node_id = str(node.get("id") or "")
        node_title = str(node.get("title") or "").strip() or "未命名章节"
        current_status = section_status_map.get(node_id) or inherited_status
        children = build_technical_coverage_tree(
            node.get("children") or [],
            section_status_map,
            current_status,
        )
        if children:
            avg = sum(int(child.get("coverage") or 0) for child in children) / len(children)
            tree.append(
                {
                    "id": node_id,
                    "title": node_title,
                    "coverage": round(avg),
                    "children": children,
                }
            )
            continue

        leaf_status = current_status or "none"
        tree.append(
            {
                "id": node_id,
                "title": node_title,
                "status": leaf_status,
                "coverage": {"full": 100, "partial": 50, "none": 0}.get(leaf_status, 0),
                "children": [],
            }
        )
    return tree


def build_technical_coverage_issue_lists(
    tree: list[dict[str, Any]],
    path: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    partial_items: list[dict[str, Any]] = []
    no_cover_items: list[dict[str, Any]] = []
    current_path = path or []
    for node in tree:
        next_path = [*current_path, str(node.get("title") or "未命名章节")]
        children = list(node.get("children") or [])
        if children:
            nested_partial, nested_none = build_technical_coverage_issue_lists(children, next_path)
            partial_items.extend(nested_partial)
            no_cover_items.extend(nested_none)
            continue

        item = {
            "id": str(node.get("id") or ""),
            "title": str(node.get("title") or "未命名章节"),
            "nodeTitle": " / ".join(current_path) if current_path else str(node.get("title") or "未命名章节"),
            "status": str(node.get("status") or "none"),
        }
        if item["status"] == "partial":
            partial_items.append(item)
        elif item["status"] == "none":
            no_cover_items.append(item)
    return partial_items, no_cover_items


def summarize_technical_coverage_tree(tree: list[dict[str, Any]]) -> tuple[int, int, int]:
    full_cover = 0
    partial_cover = 0
    no_cover = 0

    def visit(node: dict[str, Any]) -> None:
        nonlocal full_cover, partial_cover, no_cover
        children = list(node.get("children") or [])
        if children:
            for child in children:
                visit(child)
            return

        status = str(node.get("status") or "none")
        if status == "full":
            full_cover += 1
        elif status == "partial":
            partial_cover += 1
        else:
            no_cover += 1

    for node in tree:
        visit(node)
    return full_cover, partial_cover, no_cover
