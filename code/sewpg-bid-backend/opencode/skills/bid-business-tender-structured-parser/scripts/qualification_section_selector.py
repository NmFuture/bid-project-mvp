from __future__ import annotations

import re
from typing import Any


QUALIFICATION_SECTION_TREE_KEYWORDS = (
    "投标人资格要求",
    "供应商资格要求",
    "框架供应商资格要求",
    "资格能力要求",
    "资质条件、能力和信誉",
    "资格条件",
    "通用资格条件",
    "专用资格条件",
)
PRIMARY_QUALIFICATION_SECTION_TREE_KEYWORDS = (
    "投标人资格要求",
    "供应商资格要求",
    "框架供应商资格要求",
    "资格能力要求",
    "资质条件、能力和信誉",
)
NON_QUALIFICATION_SECTION_TREE_TITLE_KEYWORDS = (
    "资格要求相关证明材料",
    "资格审查资料",
    "证明材料",
    "复印件",
    "扫描件",
)
ANNOUNCEMENT_PATH_KEYWORDS = (
    "第一章",
    "第1章",
    "招标公告",
    "采购公告",
    "投标邀请",
    "采购邀请",
    "谈判采购公告",
    "询比采购公告",
    "竞争性谈判公告",
)
BIDDER_INSTRUCTION_PATH_KEYWORDS = (
    "第二章",
    "第2章",
    "投标人须知",
    "供应商须知",
    "1.4",
)
NON_TARGET_PATH_KEYWORDS = (
    "投标文件格式",
    "响应文件格式",
    "资格证明文件",
    "资格审查资料",
    "资格要求相关证明材料",
    "证明材料",
    "复印件",
    "扫描件",
)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u3000", " ")).strip()


def _section_node_path_text(node: dict[str, Any]) -> str:
    path = " ".join(str(item or "") for item in node.get("path") or [])
    return f"{path} {node.get('title') or ''}".strip()


def _leading_number_tuple(text: str) -> tuple[int, ...]:
    cleaned = _clean(text)
    match = re.match(r"^\s*(\d+(?:\.\d+)*)(?:[.．]\s*|\s+)", cleaned)
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split(".") if part.isdigit())


def _node_number_tuple(node: dict[str, Any]) -> tuple[int, ...]:
    number = str(node.get("number") or "")
    title = str(node.get("title") or "")
    return _leading_number_tuple(number) or _leading_number_tuple(title)


def _is_valid_scope_node(node: dict[str, Any], document_id: str) -> bool:
    if str(node.get("documentId") or "") != document_id:
        return False
    start_line = int(node.get("startLine") or 0)
    end_line = int(node.get("endLine") or 0)
    return start_line > 0 and end_line >= start_line


def _qualification_scope_nodes(section_tree: dict[str, Any] | None, document_id: str) -> list[dict[str, Any]]:
    if not isinstance(section_tree, dict):
        return []
    matched: list[dict[str, Any]] = []
    for node in section_tree.get("nodes") or []:
        if not isinstance(node, dict) or not _is_valid_scope_node(node, document_id):
            continue
        title = str(node.get("title") or "")
        if not any(keyword in title for keyword in QUALIFICATION_SECTION_TREE_KEYWORDS):
            continue
        if any(keyword in title for keyword in NON_QUALIFICATION_SECTION_TREE_TITLE_KEYWORDS):
            continue
        path_text = _section_node_path_text(node)
        if any(keyword in path_text for keyword in NON_TARGET_PATH_KEYWORDS):
            continue
        matched.append(node)
    return sorted(matched, key=lambda item: (int(item.get("startLine") or 0), int(item.get("level") or 9)))


def _is_primary_qualification_node(node: dict[str, Any]) -> bool:
    title = str(node.get("title") or "")
    return any(keyword in title for keyword in PRIMARY_QUALIFICATION_SECTION_TREE_KEYWORDS)


def _node_score(node: dict[str, Any]) -> int:
    title = str(node.get("title") or "")
    path_text = _section_node_path_text(node)
    number_parts = _node_number_tuple(node)
    level = int(node.get("level") or 9)
    score = 0

    if _is_primary_qualification_node(node):
        score += 1000
    elif any(keyword in title for keyword in ("通用资格条件", "专用资格条件", "资格条件")):
        score += 420

    if any(keyword in path_text for keyword in ANNOUNCEMENT_PATH_KEYWORDS):
        score += 520
    if any(keyword in path_text for keyword in BIDDER_INSTRUCTION_PATH_KEYWORDS):
        score -= 650

    if number_parts:
        if len(number_parts) == 1 and number_parts[0] == 3:
            score += 320
        elif number_parts[:2] == (1, 4):
            score -= 720
        elif number_parts[0] == 3:
            score += 140

    score += max(0, 120 - level * 20)
    return score


def _is_descendant_node(parent: dict[str, Any], child: dict[str, Any]) -> bool:
    if parent is child:
        return False
    parent_title = str(parent.get("title") or "")
    child_path = [str(item or "") for item in child.get("path") or []]
    if parent_title and parent_title in child_path[:-1]:
        return True

    parent_start = int(parent.get("startLine") or 0)
    parent_end = int(parent.get("endLine") or 0)
    child_start = int(child.get("startLine") or 0)
    child_end = int(child.get("endLine") or 0)
    parent_level = int(parent.get("level") or 9)
    child_level = int(child.get("level") or 9)
    return parent_start <= child_start and child_end <= parent_end and parent_level < child_level


def _without_descendants(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for node in nodes:
        if any(_is_descendant_node(parent, node) for parent in nodes):
            continue
        selected.append(node)
    return selected


def select_qualification_section_nodes(section_tree: dict[str, Any] | None, document_id: str) -> list[dict[str, Any]]:
    candidates = _qualification_scope_nodes(section_tree, document_id)
    if not candidates:
        return []

    scored = [(node, _node_score(node)) for node in _without_descendants(candidates)]
    if not scored:
        return []
    best_score = max(score for _node, score in scored)
    best_nodes = [node for node, score in scored if score == best_score]
    return sorted(_without_descendants(best_nodes), key=lambda item: (int(item.get("startLine") or 0), int(item.get("level") or 9)))
