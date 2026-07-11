from __future__ import annotations

from typing import Any, Awaitable, Callable

from sqlalchemy import desc, select

from app.models import async_session
from app.models.materials import WikiAttachment, WikiDoc, WikiNode
from app.services.material_taxonomy import PLATFORM_WIKI_SECTION_TITLES
from app.services.material_wiki_attachment_operations import purge_wiki_attachment_object
from app.services.material_wiki_import import (
    AUTO_WIKI_DOC_SUMMARY,
    build_generated_wiki_root_spec,
    generated_wiki_import_message,
    normalize_wiki_import_mode,
    wiki_import_node_bid_types,
    wiki_import_node_markdown,
    wiki_import_node_tags,
    wiki_import_node_title,
)
from app.services.material_wiki_scope import normalize_wiki_bid_type
from app.services.peripheral import PeripheralError


EnsureRuntimeTables = Callable[[Any], Awaitable[None]]
WikiListLoader = Callable[[str, str], Awaitable[dict[str, Any]]]


async def import_generated_wiki_blueprint_operation(
    *,
    root_title: str,
    root_markdown_content: str = "",
    nodes: list[dict[str, Any]],
    mode: str = "create",
    bid_type: str,
    ensure_runtime_tables: EnsureRuntimeTables,
    wiki_list: WikiListLoader,
) -> dict[str, Any]:
    async with async_session() as session:
        await ensure_runtime_tables(session)
        normalized_bid_type = normalize_wiki_bid_type(bid_type)
        if not normalized_bid_type:
            raise PeripheralError(400, "Wiki 导入标类不能为空。", "WIKI_IMPORT_BID_TYPE_REQUIRED")
        normalized_mode = normalize_wiki_import_mode(mode)
        root_spec = build_generated_wiki_root_spec(
            root_title=root_title,
            root_markdown_content=root_markdown_content,
            nodes=nodes,
        )
        if normalized_bid_type not in {str(item) for item in root_spec.get("applicableTypes") or []}:
            raise PeripheralError(400, "Wiki 根节点标类与当前素材库不一致。", "WIKI_IMPORT_SCOPE")
        normalized_root_title = str(root_spec["title"])

        async def purge_wiki_root(root: WikiNode) -> None:
            all_nodes = (await session.execute(select(WikiNode))).scalars().all()
            nodes_by_id = {int(node.id): node for node in all_nodes}
            children_by_parent: dict[int, list[WikiNode]] = {}
            for node in all_nodes:
                if node.parent_id is not None:
                    children_by_parent.setdefault(node.parent_id, []).append(node)

            node_ids: set[int] = set()
            node_depths: dict[int, int] = {}

            def collect(node: WikiNode, depth: int = 0) -> None:
                node_ids.add(int(node.id))
                node_depths[int(node.id)] = depth
                for child in children_by_parent.get(node.id, []):
                    collect(child, depth + 1)

            collect(root)
            if node_ids:
                attachments = (
                    await session.execute(
                        select(WikiAttachment)
                        .join(WikiDoc, WikiAttachment.doc_id == WikiDoc.id)
                        .where(WikiDoc.node_id.in_(node_ids))
                    )
                ).scalars().all()
                for attachment in attachments:
                    purge_wiki_attachment_object(attachment)
            for node_id in sorted(node_ids - {int(root.id)}, key=lambda item: node_depths.get(item, 0), reverse=True):
                node = nodes_by_id.get(node_id)
                if node is not None:
                    await session.delete(node)
            await session.delete(root)
            await session.flush()

        async def purge_orphaned_platform_sections() -> None:
            orphaned_roots = (
                await session.execute(
                    select(WikiNode).where(
                        WikiNode.parent_id.is_(None),
                        WikiNode.title.in_(PLATFORM_WIKI_SECTION_TITLES),
                    )
                )
            ).scalars().all()
            for orphaned_root in orphaned_roots:
                await purge_wiki_root(orphaned_root)

        async def create_node(
            spec: dict[str, Any],
            parent: WikiNode | None,
            *,
            default_tier: str = "standard",
            sort_order: int = 0,
        ) -> WikiNode:
            title = wiki_import_node_title(spec)
            path = f"{parent.path if parent else ''}/{title}".lstrip("/")
            node = WikiNode(
                parent_id=parent.id if parent else None,
                title=title,
                tier=parent.tier if parent else default_tier,
                path=path,
                bid_types=wiki_import_node_bid_types(spec),
                sort_order=sort_order,
            )
            session.add(node)
            await session.flush()
            doc = WikiDoc(
                node_id=node.id,
                markdown_content=wiki_import_node_markdown(spec, title),
                ai_summary=AUTO_WIKI_DOC_SUMMARY,
                tags=wiki_import_node_tags(spec),
            )
            session.add(doc)
            await session.flush()
            for index, child in enumerate(spec.get("children") or []):
                if isinstance(child, dict):
                    await create_node(child, node, default_tier=default_tier, sort_order=index)
            return node

        async def upsert_node(spec: dict[str, Any], parent: WikiNode, *, sort_order: int = 0) -> WikiNode:
            title = wiki_import_node_title(spec)
            result = await session.execute(
                select(WikiNode)
                .where(WikiNode.parent_id == parent.id, WikiNode.title == title)
                .order_by(desc(WikiNode.created_at), desc(WikiNode.id))
            )
            duplicate_nodes = result.scalars().all()
            node = duplicate_nodes[0] if duplicate_nodes else None
            if node is None:
                node = await create_node(spec, parent, sort_order=sort_order)
            else:
                for duplicate_node in duplicate_nodes[1:]:
                    await purge_wiki_root(duplicate_node)
                node.path = f"{parent.path}/{title}".lstrip("/")
                node.bid_types = wiki_import_node_bid_types(spec, list(node.bid_types or []))
                node.sort_order = sort_order
                doc_result = await session.execute(select(WikiDoc).where(WikiDoc.node_id == node.id))
                docs = doc_result.scalars().all()
                doc = docs[0] if docs else None
                for duplicate_doc in docs[1:]:
                    await session.delete(duplicate_doc)
                if doc is None:
                    session.add(
                        WikiDoc(
                            node_id=node.id,
                            markdown_content=wiki_import_node_markdown(spec, title),
                            ai_summary=AUTO_WIKI_DOC_SUMMARY,
                            tags=wiki_import_node_tags(spec),
                        )
                    )
                else:
                    doc.markdown_content = wiki_import_node_markdown(spec, title, doc.markdown_content or "")
                    doc.ai_summary = doc.ai_summary or AUTO_WIKI_DOC_SUMMARY
                    doc.tags = wiki_import_node_tags(spec, list(doc.tags or []))
                await session.flush()
                for child_index, child in enumerate(spec.get("children") or []):
                    if isinstance(child, dict):
                        await upsert_node(child, node, sort_order=child_index)
            return node

        async def sync_children_to_specs(parent: WikiNode, specs: list[dict[str, Any]]) -> None:
            desired_titles: set[str] = set()
            for index, child in enumerate(specs):
                if not isinstance(child, dict):
                    continue
                desired_titles.add(wiki_import_node_title(child))
                node = await upsert_node(child, parent, sort_order=index)
                child_specs = [item for item in (child.get("children") or []) if isinstance(item, dict)]
                await sync_children_to_specs(node, child_specs)

            existing_children = (
                await session.execute(select(WikiNode).where(WikiNode.parent_id == parent.id))
            ).scalars().all()
            for child in existing_children:
                if child.title not in desired_titles:
                    await purge_wiki_root(child)

        existing_roots = (
            await session.execute(
                select(WikiNode)
                .where(WikiNode.parent_id.is_(None), WikiNode.title == normalized_root_title)
                .order_by(desc(WikiNode.created_at), desc(WikiNode.id))
            )
        ).scalars().all()

        if normalized_mode == "replace":
            for root in existing_roots:
                await purge_wiki_root(root)
            await purge_orphaned_platform_sections()
            root_node = await create_node(root_spec, None)
            message = generated_wiki_import_message(normalized_root_title, "replaced")
        elif existing_roots:
            root_node = existing_roots[0]
            for duplicate_root in existing_roots[1:]:
                await purge_wiki_root(duplicate_root)
            await purge_orphaned_platform_sections()
            if normalized_mode in {"update", "refresh"}:
                root_node.title = normalized_root_title
                root_node.path = normalized_root_title
                root_node.bid_types = list(root_spec["applicableTypes"])
                doc_result = await session.execute(select(WikiDoc).where(WikiDoc.node_id == root_node.id))
                root_doc = doc_result.scalar_one_or_none()
                if root_doc is None:
                    session.add(
                        WikiDoc(
                            node_id=root_node.id,
                            markdown_content=root_spec["markdownContent"],
                            ai_summary=AUTO_WIKI_DOC_SUMMARY,
                            tags=list(root_spec["tags"]),
                        )
                    )
                else:
                    root_doc.markdown_content = root_spec["markdownContent"]
                    root_doc.tags = list(root_spec["tags"])
                children = [child for child in (root_spec.get("children") or []) if isinstance(child, dict)]
                if normalized_mode == "refresh":
                    await sync_children_to_specs(root_node, children)
                else:
                    for index, child in enumerate(children):
                        await upsert_node(child, root_node, sort_order=index)
                if normalized_mode == "refresh":
                    message = generated_wiki_import_message(normalized_root_title, "refreshed")
                else:
                    message = generated_wiki_import_message(normalized_root_title, "updated")
            else:
                message = generated_wiki_import_message(normalized_root_title, "kept")
        else:
            root_node = await create_node(root_spec, None)
            message = generated_wiki_import_message(normalized_root_title, "created")

        root_node_id = int(root_node.id)
        await session.commit()

    return {"message": message, "mode": normalized_mode, **await wiki_list(f"WIKI-{root_node_id:04d}", normalized_bid_type)}
