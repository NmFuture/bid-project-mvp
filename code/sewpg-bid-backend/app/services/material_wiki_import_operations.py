from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from sqlalchemy import desc, select

from app.models import async_session
from app.models.materials import WikiAttachment, WikiDoc, WikiNode

logger = logging.getLogger(__name__)
from app.services.material_taxonomy import PLATFORM_WIKI_SECTION_TITLES
from app.services.material_wiki_attachment_operations import purge_wiki_attachment_object
from app.services.material_wiki_import import (
    AUTO_WIKI_DOC_SUMMARY,
    build_generated_wiki_root_spec,
    generated_wiki_import_message,
    is_generated_wiki_doc,
    normalize_wiki_import_mode,
    wiki_import_node_bid_types,
    wiki_import_node_markdown,
    wiki_import_node_tags,
    wiki_import_node_title,
    with_generated_wiki_tag,
)
from app.services.material_wiki_scope import normalize_wiki_bid_type
from app.services.peripheral import PeripheralError


PROGRESS_TICK_STEP = 25

EnsureRuntimeTables = Callable[[Any], Awaitable[None]]
WikiListLoader = Callable[[str, str], Awaitable[dict[str, Any]]]


def count_wiki_node_specs(specs: list[dict[str, Any]]) -> int:
    """递归统计蓝图节点数，作为导入进度的分母。"""
    total = 0
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        total += 1
        total += count_wiki_node_specs([
            child for child in (spec.get("children") or []) if isinstance(child, dict)
        ])
    return total


async def import_generated_wiki_blueprint_operation(
    *,
    root_title: str,
    root_markdown_content: str = "",
    nodes: list[dict[str, Any]],
    mode: str = "create",
    bid_type: str,
    ensure_runtime_tables: EnsureRuntimeTables,
    wiki_list: WikiListLoader,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    # on_progress 可选：只有技术标自动流水线传入用于进度条，商务标不传行为不变。
    # 每 PROGRESS_TICK_STEP 个节点回报一次，避免上千节点时把队列状态写爆。
    total_node_specs = count_wiki_node_specs(nodes)
    imported_node_count = 0

    def tick_node_progress() -> None:
        nonlocal imported_node_count
        imported_node_count += 1
        if on_progress is None:
            return
        if imported_node_count % PROGRESS_TICK_STEP == 0 or imported_node_count >= total_node_specs:
            on_progress({"done": min(imported_node_count, total_node_specs), "total": total_node_specs})

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
        # 事务内先累积待清理的 MinIO 对象，提交成功后再统一删除；删对象失败只记警告，
        # 保证不会出现「对象已删、DB 记录回滚保留」的悬空记录。
        pending_object_purges: list[WikiAttachment] = []

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
                node_key = int(node.id)
                if node_key in node_ids:  # visited 防护：环或重复父子关系不再无限递归
                    logger.warning("wiki purge 检测到重复节点，已跳过防止无限递归：node_id=%s", node_key)
                    return
                node_ids.add(node_key)
                node_depths[node_key] = depth
                for child in children_by_parent.get(node_key, []):
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
                pending_object_purges.extend(attachments)
            for node_id in sorted(node_ids - {int(root.id)}, key=lambda item: node_depths.get(item, 0), reverse=True):
                node = nodes_by_id.get(node_id)
                if node is not None:
                    await session.delete(node)
            await session.delete(root)
            await session.flush()

        async def node_is_generated(node: WikiNode) -> bool:
            """节点是否由 import 生成链路创建（依据其 WikiDoc 的来源标记 tag）。"""
            doc_result = await session.execute(select(WikiDoc).where(WikiDoc.node_id == node.id))
            docs = doc_result.scalars().all()
            if not docs:
                # 无 doc 的节点无法确认来源，保守视为手工节点予以保留。
                return False
            return any(is_generated_wiki_doc(doc.tags) for doc in docs)

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
            counted: bool = True,
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
                tags=with_generated_wiki_tag(wiki_import_node_tags(spec)),
            )
            session.add(doc)
            await session.flush()
            if counted:
                tick_node_progress()
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
                    # 只清理自动生成的重复项；同名手工节点保留，避免刷新时误删人工内容。
                    if await node_is_generated(duplicate_node):
                        await purge_wiki_root(duplicate_node)
                    else:
                        logger.warning(
                            "wiki upsert 保留同名手工节点，未删除：node_id=%s title=%s",
                            int(duplicate_node.id),
                            title,
                        )
                tick_node_progress()
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
                            tags=with_generated_wiki_tag(wiki_import_node_tags(spec)),
                        )
                    )
                else:
                    doc.markdown_content = wiki_import_node_markdown(spec, title, doc.markdown_content or "")
                    doc.ai_summary = doc.ai_summary or AUTO_WIKI_DOC_SUMMARY
                    doc.tags = with_generated_wiki_tag(wiki_import_node_tags(spec, list(doc.tags or [])))
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
                if child.title in desired_titles:
                    continue
                # 只删除自动生成来源的落选节点；用户手工新建的节点一律保留并记警告。
                if await node_is_generated(child):
                    await purge_wiki_root(child)
                else:
                    logger.warning(
                        "wiki refresh 保留手工节点（不在本次蓝图内）：node_id=%s title=%s",
                        int(child.id),
                        child.title,
                    )

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
            root_node = await create_node(root_spec, None, counted=False)
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
                            tags=with_generated_wiki_tag(list(root_spec["tags"])),
                        )
                    )
                else:
                    root_doc.markdown_content = root_spec["markdownContent"]
                    root_doc.tags = with_generated_wiki_tag(list(root_spec["tags"]))
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
            root_node = await create_node(root_spec, None, counted=False)
            message = generated_wiki_import_message(normalized_root_title, "created")

        root_node_id = int(root_node.id)
        await session.commit()

    # DB 提交成功后再清理 MinIO 对象；删对象失败只记警告，孤儿对象可接受，悬空记录不可接受。
    for attachment in pending_object_purges:
        try:
            purge_wiki_attachment_object(attachment)
        except Exception:  # noqa: BLE001 - 对象清理失败不影响已提交的删除结果
            logger.warning("wiki import 清理 MinIO 附件对象失败：attachment_id=%s", getattr(attachment, "id", ""), exc_info=True)

    return {"message": message, "mode": normalized_mode, **await wiki_list(f"WIKI-{root_node_id:04d}", normalized_bid_type)}
