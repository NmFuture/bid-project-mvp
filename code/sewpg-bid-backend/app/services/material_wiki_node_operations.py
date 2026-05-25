from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import async_session
from app.models.materials import WikiAttachment, WikiDoc, WikiNode
from app.services.material_wiki_attachment_operations import purge_wiki_attachment_object
from app.services.material_wiki_scope import wiki_node_bid_types
from app.services.peripheral import PeripheralError


EnsureRuntimeTables = Callable[[Any], Awaitable[None]]
WikiListLoader = Callable[[str, str], Awaitable[dict[str, Any]]]


async def create_wiki_node(
    *,
    parent_id: str,
    title: str,
    is_folder: bool,
    bid_type: str,
    ensure_runtime_tables: EnsureRuntimeTables,
    wiki_list: WikiListLoader,
) -> dict[str, Any]:
    async with async_session() as session:
        await ensure_runtime_tables(session)
        parent = None
        if parent_id:
            numeric_parent = int(parent_id.replace("WIKI-", ""))
            result = await session.execute(select(WikiNode).where(WikiNode.id == numeric_parent))
            parent = result.scalar_one_or_none()

        path = f"{parent.path if parent else ''}/{title}".lstrip("/")
        node = WikiNode(
            parent_id=parent.id if parent else None,
            title=title.strip() or ("新建目录" if is_folder else "新建节点"),
            tier=parent.tier if parent else "standard",
            path=path,
            bid_types=wiki_node_bid_types(
                parent_bid_types=parent.bid_types if parent else None,
                bid_type=bid_type,
            ),
        )
        session.add(node)
        await session.flush()

        doc = WikiDoc(
            node_id=node.id,
            markdown_content=f"# {node.title}\n\n请在此补充节点内容。",
            ai_summary="新建节点，尚未生成摘要。",
        )
        session.add(doc)
        await session.commit()
        node_id = f"WIKI-{node.id:04d}"

    return {"message": "Created", **await wiki_list(node_id, bid_type)}


async def update_wiki_node(
    *,
    node_id: str,
    data: dict[str, Any],
    bid_type: str,
    ensure_runtime_tables: EnsureRuntimeTables,
    wiki_list: WikiListLoader,
) -> dict[str, Any]:
    numeric_id = int(node_id.replace("WIKI-", ""))
    async with async_session() as session:
        await ensure_runtime_tables(session)
        result = await session.execute(
            select(WikiDoc).where(WikiDoc.node_id == numeric_id).options(selectinload(WikiDoc.node))
        )
        doc = result.scalar_one_or_none()
        if doc is None:
            raise PeripheralError(404, "Wiki 节点不存在。", "WIKI_NODE_NOT_FOUND")

        if data.get("title"):
            doc.node.title = str(data["title"])
            doc.node.path = "/".join(doc.node.path.split("/")[:-1] + [doc.node.title])
        if data.get("markdownContent") is not None:
            doc.markdown_content = str(data["markdownContent"])
        if data.get("tags") is not None:
            doc.tags = list(data["tags"])
        if data.get("applicableTypes") is not None:
            doc.node.bid_types = list(data["applicableTypes"])

        await session.commit()

    return {"message": "Updated", **await wiki_list(node_id, bid_type)}


async def delete_wiki_node(
    *,
    node_id: str,
    bid_type: str,
    ensure_runtime_tables: EnsureRuntimeTables,
    wiki_list: WikiListLoader,
) -> dict[str, Any]:
    numeric_id = int(node_id.replace("WIKI-", ""))
    async with async_session() as session:
        await ensure_runtime_tables(session)
        result = await session.execute(select(WikiNode).where(WikiNode.id == numeric_id))
        node = result.scalar_one_or_none()
        if node is None:
            raise PeripheralError(404, "Wiki 节点不存在。", "WIKI_NODE_NOT_FOUND")

        all_nodes = (await session.execute(select(WikiNode))).scalars().all()
        children_by_parent: dict[int, list[WikiNode]] = {}
        for item in all_nodes:
            if item.parent_id is not None:
                children_by_parent.setdefault(int(item.parent_id), []).append(item)

        node_ids: set[int] = set()
        node_depths: dict[int, int] = {}

        def collect(current: WikiNode, depth: int = 0) -> None:
            node_ids.add(int(current.id))
            node_depths[int(current.id)] = depth
            for child in children_by_parent.get(int(current.id), []):
                collect(child, depth + 1)

        collect(node)
        docs = (
            await session.execute(select(WikiDoc).where(WikiDoc.node_id.in_(node_ids)))
        ).scalars().all()
        doc_ids = [int(doc.id) for doc in docs]
        attachments: list[WikiAttachment] = []
        if doc_ids:
            attachments = (
                await session.execute(select(WikiAttachment).where(WikiAttachment.doc_id.in_(doc_ids)))
            ).scalars().all()
        for attachment in attachments:
            purge_wiki_attachment_object(attachment)

        nodes_by_id = {int(item.id): item for item in all_nodes if int(item.id) in node_ids}
        for item_id in sorted(node_ids, key=lambda value: node_depths.get(value, 0), reverse=True):
            item = nodes_by_id.get(item_id)
            if item is not None:
                await session.delete(item)
        deleted_count = len(node_ids)
        await session.commit()

    return {
        "message": f"Wiki 节点删除成功，共删除 {deleted_count} 个节点。",
        "deletedNodeCount": deleted_count,
        **await wiki_list("", bid_type),
    }


async def refresh_wiki_summary(
    *,
    node_id: str,
    bid_type: str,
    ensure_runtime_tables: EnsureRuntimeTables,
    wiki_list: WikiListLoader,
) -> dict[str, Any]:
    numeric_id = int(node_id.replace("WIKI-", ""))
    async with async_session() as session:
        await ensure_runtime_tables(session)
        result = await session.execute(select(WikiDoc).where(WikiDoc.node_id == numeric_id))
        doc = result.scalar_one_or_none()
        if doc is None:
            raise PeripheralError(404, "Wiki 节点不存在。", "WIKI_NODE_NOT_FOUND")
        text = doc.markdown_content or ""
        summary = re.sub(r"\s+", " ", text.replace("#", "")).strip()[:80] or "暂无摘要。"
        doc.ai_summary = summary
        await session.commit()

    return {"summary": summary, **await wiki_list(node_id, bid_type)}


async def move_wiki_node(
    *,
    node_id: str,
    target_id: str,
    mode: str,
    bid_type: str,
    ensure_runtime_tables: EnsureRuntimeTables,
    wiki_list: WikiListLoader,
) -> dict[str, Any]:
    numeric_id = int(node_id.replace("WIKI-", ""))
    target_numeric = int(target_id.replace("WIKI-", ""))
    async with async_session() as session:
        await ensure_runtime_tables(session)
        result = await session.execute(select(WikiNode).where(WikiNode.id == numeric_id))
        source = result.scalar_one_or_none()
        if source is None:
            raise PeripheralError(404, "Wiki 节点不存在。", "WIKI_NODE_NOT_FOUND")
        result2 = await session.execute(
            select(WikiNode).where(WikiNode.id == target_numeric).options(selectinload(WikiNode.parent))
        )
        target = result2.scalar_one_or_none()
        if target is None:
            raise PeripheralError(404, "目标节点不存在。", "WIKI_NODE_NOT_FOUND")
        source.parent_id = target.id if mode == "inside" else target.parent_id
        source.path = f"{target.path if mode == 'inside' else (target.parent.path if target.parent else '')}/{source.title}".lstrip("/")
        await session.commit()

    return {"message": "Moved", **await wiki_list(node_id, bid_type)}
