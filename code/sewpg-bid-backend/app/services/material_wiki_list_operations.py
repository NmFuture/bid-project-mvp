from __future__ import annotations

from typing import Any, Awaitable, Callable

from sqlalchemy import desc, select
from sqlalchemy.orm import selectinload

from app.models import async_session
from app.models.materials import WikiAttachment, WikiDoc, WikiNode
from app.services.material_wiki_attachment_operations import wiki_attachment_to_dict
from app.services.material_wiki_scope import WIKI_APPLICABLE_TYPE_OPTIONS, WIKI_TAG_OPTIONS
from app.services.material_wiki_tree import build_wiki_tree_context


EnsureRuntimeTables = Callable[[Any], Awaitable[None]]


async def wiki_list_operation(
    *,
    bid_type: str,
    node_id: str = "",
    ensure_runtime_tables: EnsureRuntimeTables,
) -> dict[str, Any]:
    async with async_session() as session:
        await ensure_runtime_tables(session)
        nodes_result = await session.execute(select(WikiNode).order_by(WikiNode.sort_order, WikiNode.id))
        all_nodes = nodes_result.scalars().all()
        tags_result = await session.execute(select(WikiDoc.node_id, WikiDoc.tags))
        tags_by_node_id = {
            int(numeric_id): list(tags or [])
            for numeric_id, tags in tags_result.all()
        }
        tree_context = build_wiki_tree_context(
            all_nodes=list(all_nodes),
            node_id=node_id,
            bid_type=bid_type,
            tags_by_node_id=tags_by_node_id,
        )
        visible_node_ids = tree_context["visibleNodeIds"]
        normalized_bid_type = tree_context["normalizedBidType"]

        selected = None
        for numeric_id in tree_context["selectedNodeIds"]:
            if normalized_bid_type and numeric_id not in visible_node_ids:
                continue
            if not normalized_bid_type or numeric_id in visible_node_ids:
                doc_result = await session.execute(
                    select(WikiDoc).where(WikiDoc.node_id == numeric_id).options(selectinload(WikiDoc.node))
                )
                doc = doc_result.scalar_one_or_none()
                if doc:
                    selected = doc.to_dict()
                    attachment_rows = (
                        await session.execute(
                            select(WikiAttachment)
                            .where(WikiAttachment.doc_id == doc.id)
                            .order_by(desc(WikiAttachment.created_at), desc(WikiAttachment.id))
                        )
                    ).scalars().all()
                    selected["attachments"] = [wiki_attachment_to_dict(item) for item in attachment_rows]
                    break

        return {
            "tree": tree_context["tree"],
            "selectedNode": selected,
            "tagOptions": WIKI_TAG_OPTIONS,
            "applicableTypeOptions": WIKI_APPLICABLE_TYPE_OPTIONS,
        }
