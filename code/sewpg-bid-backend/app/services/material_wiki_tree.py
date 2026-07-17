from __future__ import annotations

from typing import Any

from app.services.material_wiki_scope import normalize_wiki_bid_type, wiki_root_visible_for_bid_type


def build_wiki_tree_context(
    *,
    all_nodes: list[Any],
    bid_type: str,
    node_id: str = "",
    tags_by_node_id: dict[int, list[str]] | None = None,
) -> dict[str, Any]:
    normalized_bid_type = normalize_wiki_bid_type(bid_type)
    normalized_tags = tags_by_node_id or {}
    children_by_parent: dict[int, list[Any]] = {}
    for node in all_nodes:
        parent_id = getattr(node, "parent_id", None)
        if parent_id is not None:
            children_by_parent.setdefault(int(parent_id), []).append(node)

    visible_node_ids: set[int] = set()
    visible_node_order: list[int] = []

    def collect_visible(node: Any) -> None:
        node_id_int = int(getattr(node, "id"))
        visible_node_ids.add(node_id_int)
        visible_node_order.append(node_id_int)
        for child in children_by_parent.get(node_id_int, []):
            collect_visible(child)

    def build_node(node: Any) -> dict[str, Any]:
        node_id_int = int(getattr(node, "id"))
        child_nodes = children_by_parent.get(node_id_int, [])
        has_children = bool(child_nodes)
        return {
            "id": f"WIKI-{node_id_int:04d}",
            "title": getattr(node, "title"),
            "icon": "folder" if has_children else "article",
            "expanded": True if has_children else None,
            "tags": list(normalized_tags.get(node_id_int) or []),
            "children": [build_node(child) for child in child_nodes],
        }

    roots = [
        node
        for node in all_nodes
        if getattr(node, "parent_id", None) is None
        and wiki_root_visible_for_bid_type(
            title=str(getattr(node, "title", "") or ""),
            bid_types=getattr(node, "bid_types", None) or [],
            bid_type=normalized_bid_type,
        )
    ]
    for root in roots:
        collect_visible(root)

    selected_node_ids: list[int] = []
    if node_id:
        selected_node_ids.append(int(str(node_id).replace("WIKI-", "")))
    selected_node_ids.extend(item for item in visible_node_order if item not in selected_node_ids)

    return {
        "tree": [build_node(root) for root in roots],
        "selectedNodeIds": selected_node_ids,
        "visibleNodeIds": visible_node_ids,
        "normalizedBidType": normalized_bid_type,
    }
