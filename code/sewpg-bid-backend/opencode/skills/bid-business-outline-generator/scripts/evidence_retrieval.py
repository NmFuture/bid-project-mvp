from __future__ import annotations

from typing import Any


def retrieve_evidence_for_section(
    section: dict[str, Any],
    source_set: Any,
    parent_anchors: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ranked evidence candidates for one outline section.

    The implementation is imported lazily to keep this module as the stable
    retrieval boundary without duplicating the mature ranking logic.
    """

    from resolve_source_text_candidates import find_candidates

    return find_candidates(section, source_set, parent_anchors)


def retrieve_evidence_for_outline(
    sections: list[dict[str, Any]],
    source_set: Any,
    iter_sections,
) -> list[dict[str, Any]]:
    parent_anchors: dict[str, list[dict[str, Any]]] = {}
    items: list[dict[str, Any]] = []
    for section in iter_sections(sections):
        candidates, anchors = retrieve_evidence_for_section(section, source_set, parent_anchors)
        parent_anchors[section.get("id")] = anchors
        items.append(
            {
                "id": section.get("id"),
                "title": section.get("title"),
                "source_text": section.get("source_text"),
                "parent_id": section.get("parent", {}).get("id") if section.get("parent") else None,
                "candidates": candidates,
            }
        )
    return items
