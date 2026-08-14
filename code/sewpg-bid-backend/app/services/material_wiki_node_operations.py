from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import async_session
from app.models.materials import WikiDoc, WikiNode
from app.services.peripheral import PeripheralError


EnsureRuntimeTables = Callable[[Any], Awaitable[None]]
WikiListLoader = Callable[[str, str], Awaitable[dict[str, Any]]]


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
        # 只剥离每行行首的 markdown 标题符号，不误删正文中的 #。
        stripped = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
        summary = re.sub(r"\s+", " ", stripped).strip()[:80] or "暂无摘要。"
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

        # 环检测：移动后的新父节点不能是 source 自身，也不能是 source 的任一子孙，
        # 否则会形成自引用环，导致树递归（list/delete）无限递归。
        new_parent_id = target.id if mode == "inside" else target.parent_id
        if new_parent_id is not None:
            all_nodes = (await session.execute(select(WikiNode))).scalars().all()
            children_by_parent: dict[int, list[int]] = {}
            for item in all_nodes:
                if item.parent_id is not None:
                    children_by_parent.setdefault(int(item.parent_id), []).append(int(item.id))
            descendants: set[int] = set()
            stack = [int(source.id)]
            while stack:
                current = stack.pop()
                if current in descendants:  # visited 防护：已有环时不再无限循环
                    continue
                descendants.add(current)
                stack.extend(children_by_parent.get(current, []))
            if int(new_parent_id) in descendants:
                raise PeripheralError(400, "不能把节点移动到自身或其子节点下。", "WIKI_NODE_MOVE_CYCLE")

        source.parent_id = new_parent_id
        source.path = f"{target.path if mode == 'inside' else (target.parent.path if target.parent else '')}/{source.title}".lstrip("/")
        await session.commit()

    return {"message": "Moved", **await wiki_list(node_id, bid_type)}
