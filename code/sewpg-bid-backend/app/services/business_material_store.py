from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import async_session
from app.models.materials import WikiAttachment
from app.services.business_material_splitter import (
    confirm_business_material_split,
    preview_business_material_split,
)
from app.services.bid_type import BUSINESS_BID_TYPE
from app.services.material_store import material_store
from app.services.peripheral import PeripheralError
from app.services.scoped_material_urls import rewrite_material_urls


def normalize_business_material_path(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/")


def ensure_business_material_path(path: str, label: str = "路径") -> str:
    normalized = normalize_business_material_path(path)
    if normalized and normalized != BUSINESS_BID_TYPE and not normalized.startswith(f"{BUSINESS_BID_TYPE}/"):
        raise PeripheralError(400, f"{label}必须位于商务标素材库。", "BUSINESS_MATERIAL_PATH_REQUIRED")
    return normalized


def business_material_payload(data: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(data or {})
    payload["bidType"] = BUSINESS_BID_TYPE
    return payload


def _business_tree(payload: dict[str, Any]) -> dict[str, Any]:
    tree = [
        item
        for item in (payload.get("tree") or [])
        if normalize_business_material_path(str(item.get("path") or item.get("name") or "")) == BUSINESS_BID_TYPE
    ]
    return {**payload, "tree": tree}


def _force_business_tree(payload: dict[str, Any]) -> dict[str, Any]:
    if "tree" not in payload:
        return payload
    return _business_tree(payload)


def _collect_wiki_ids(nodes: list[dict[str, Any]]) -> set[str]:
    visible: set[str] = set()
    stack = list(nodes)
    while stack:
        node = stack.pop()
        node_id = str(node.get("id") or "")
        if node_id:
            visible.add(node_id)
        stack.extend(list(node.get("children") or []))
    return visible


class BusinessMaterialStore:
    @staticmethod
    def _with_urls(payload: Any) -> Any:
        return rewrite_material_urls(
            payload,
            raw_prefix="/api/business/materials/raw",
            wiki_prefix="/api/business/materials/wiki",
        )

    def ensure_path(self, path: str, label: str = "路径") -> str:
        return ensure_business_material_path(path, label)

    def ensure_parent_path(self, path: str, label: str = "父级目录") -> str:
        return self.ensure_path(path, label) or BUSINESS_BID_TYPE

    async def ensure_raw_file(self, file_id: str) -> None:
        payload = await material_store.raw_files(
            bid_type=BUSINESS_BID_TYPE,
            folder_path=BUSINESS_BID_TYPE,
            recursive=True,
            page=1,
            page_size=100000,
        )
        if not any(str(item.get("id") or "") == file_id for item in payload.get("items") or []):
            raise PeripheralError(400, "该文件不属于商务标素材库。", "BUSINESS_RAW_FILE_SCOPE")

    async def _ensure_wiki_node(self, node_id: str, label: str = "Wiki 节点") -> None:
        if not node_id:
            return
        payload = await material_store.wiki_list("", BUSINESS_BID_TYPE)
        if node_id not in _collect_wiki_ids(list(payload.get("tree") or [])):
            raise PeripheralError(400, f"{label}不属于商务标 Wiki。", "BUSINESS_WIKI_NODE_SCOPE")

    async def _ensure_wiki_attachment(self, attachment_id: str) -> None:
        numeric_id = int(str(attachment_id).replace("WIKI-ATT-", ""))
        async with async_session() as session:
            result = await session.execute(
                select(WikiAttachment)
                .where(WikiAttachment.id == numeric_id)
                .options(selectinload(WikiAttachment.doc))
            )
            attachment = result.scalar_one_or_none()
        if attachment is None:
            raise PeripheralError(404, "附件不存在。", "WIKI_ATTACHMENT_NOT_FOUND")
        node_id = int(attachment.doc.node_id) if attachment.doc else 0
        await self._ensure_wiki_node(f"WIKI-{node_id:04d}" if node_id else "", "附件")

    async def identity_options(self) -> dict[str, Any]:
        return await material_store.identity_options(bid_type=BUSINESS_BID_TYPE)

    async def raw_tree(self) -> dict[str, Any]:
        return self._with_urls(_business_tree(await material_store.raw_tree(bid_type=BUSINESS_BID_TYPE)))

    async def raw_files(
        self,
        *,
        folder_path: str = "",
        project_id: str = "",
        customer_name: str = "",
        material_tier: str = "",
        clean_status: str = "",
        business_material_kind: str = "",
        tag: Any = "",
        title: str = "",
        keyword: str = "",
        recursive: bool = True,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        return self._with_urls(await material_store.raw_files(
            bid_type=BUSINESS_BID_TYPE,
            folder_path=self.ensure_path(folder_path, "素材目录") or BUSINESS_BID_TYPE,
            project_id=project_id,
            customer_name=customer_name,
            material_tier=material_tier,
            clean_status=clean_status,
            business_material_kind=business_material_kind,
            tag=tag,
            title=title,
            keyword=keyword,
            recursive=recursive,
            page=page,
            page_size=page_size,
        ))

    async def raw_upload(
        self,
        *,
        target_path: str = "",
        project_id: str = "",
        project_code: str = "",
        project_name: str = "",
        material_tier: str = "",
        business_material_kind: str = "",
        customer_id: str = "",
        customer_name: str = "",
        tags: Any = None,
        on_conflict: str = "",
        files: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return self._with_urls(await material_store.raw_upload(
            target_path=self.ensure_path(target_path, "目标目录"),
            project_id=project_id,
            project_code=project_code,
            project_name=project_name,
            bid_type=BUSINESS_BID_TYPE,
            material_tier=material_tier,
            business_material_kind=business_material_kind,
            customer_id=customer_id,
            customer_name=customer_name,
            tags=tags,
            on_conflict=on_conflict,
            files=list(files or []),
        ))

    async def raw_create_folder(self, parent_path: str, folder_name: str) -> dict[str, Any]:
        payload = await material_store.raw_create_folder(
            parent_path=self.ensure_parent_path(parent_path, "父级目录"),
            folder_name=folder_name,
            bid_type=BUSINESS_BID_TYPE,
        )
        return self._with_urls(_force_business_tree(payload))

    async def raw_delete_folder(self, path: str) -> dict[str, Any]:
        payload = await material_store.raw_delete_folder(
            self.ensure_path(path, "目标目录"),
            bid_type=BUSINESS_BID_TYPE,
        )
        return self._with_urls(_force_business_tree(payload))

    async def raw_update_file(
        self,
        file_id: str,
        *,
        name: str = "",
        business_material_kind: str = "",
        tags: Any = None,
        update_tags: bool = False,
    ) -> dict[str, Any]:
        await self.ensure_raw_file(file_id)
        return self._with_urls(await material_store.raw_update_file(
            file_id,
            bid_type=BUSINESS_BID_TYPE,
            name=name,
            business_material_kind=business_material_kind,
            tags=tags,
            update_tags=update_tags,
        ))

    async def raw_delete_file(self, file_id: str) -> dict[str, Any]:
        await self.ensure_raw_file(file_id)
        return self._with_urls(await material_store.raw_delete_file(file_id, bid_type=BUSINESS_BID_TYPE))

    async def raw_download_file(self, file_id: str) -> dict[str, Any]:
        await self.ensure_raw_file(file_id)
        return self._with_urls(await material_store.raw_download_file(file_id, bid_type=BUSINESS_BID_TYPE))

    async def raw_cleaned_preview(
        self,
        file_id: str,
        *,
        browser_base_url: str = "",
        onlyoffice_base_url: str = "",
    ) -> dict[str, Any]:
        await self.ensure_raw_file(file_id)
        return await material_store.raw_cleaned_preview(
            file_id,
            bid_type=BUSINESS_BID_TYPE,
            browser_base_url=browser_base_url,
            onlyoffice_base_url=onlyoffice_base_url,
            content_path_prefix="/api/business/materials/raw",
        )

    async def raw_download_cleaned_content(self, file_id: str) -> dict[str, Any]:
        await self.ensure_raw_file(file_id)
        return await material_store.raw_download_cleaned_content(file_id, bid_type=BUSINESS_BID_TYPE)

    async def raw_download_content(self, file_id: str) -> dict[str, Any]:
        await self.ensure_raw_file(file_id)
        return await material_store.raw_download_content(file_id, bid_type=BUSINESS_BID_TYPE)

    async def raw_move_file(self, *, file_id: str, target_path: str, on_conflict: str = "") -> dict[str, Any]:
        await self.ensure_raw_file(file_id)
        return self._with_urls(await material_store.raw_move_file(
            file_id=file_id,
            target_path=self.ensure_path(target_path, "目标目录"),
            bid_type=BUSINESS_BID_TYPE,
            on_conflict=on_conflict,
        ))

    async def raw_move_folder(self, *, source_path: str, target_parent_path: str) -> dict[str, Any]:
        payload = await material_store.raw_move_folder(
            source_path=self.ensure_path(source_path, "源目录"),
            target_parent_path=self.ensure_parent_path(target_parent_path, "目标父级目录"),
            bid_type=BUSINESS_BID_TYPE,
        )
        return self._with_urls(_force_business_tree(payload))

    async def preview_business_split(self, file_id: str, *, target_path: str, ai_mode: str) -> dict[str, Any]:
        await self.ensure_raw_file(file_id)
        return await preview_business_material_split(
            file_id=file_id,
            target_path=self.ensure_path(target_path, "目标目录"),
            ai_mode=ai_mode,
        )

    async def confirm_business_split(
        self,
        file_id: str,
        *,
        fragments: list[dict[str, Any]],
        target_path: str = "",
        on_conflict: str = "",
    ) -> dict[str, Any]:
        await self.ensure_raw_file(file_id)
        return await confirm_business_material_split(
            file_id=file_id,
            fragments=fragments,
            default_target_path=self.ensure_path(target_path, "目标目录"),
            on_conflict=on_conflict,
        )

    async def wiki_list(self, node_id: str = "") -> dict[str, Any]:
        return self._with_urls(await material_store.wiki_list(node_id, BUSINESS_BID_TYPE))

    async def wiki_create(self, *, parent_id: str, title: str, is_folder: bool) -> dict[str, Any]:
        await self._ensure_wiki_node(parent_id, "父级 Wiki 节点")
        return self._with_urls(await material_store.wiki_create(
            parent_id=parent_id,
            title=title,
            is_folder=is_folder,
            bid_type=BUSINESS_BID_TYPE,
        ))

    async def wiki_update(self, node_id: str, data: dict[str, Any]) -> dict[str, Any]:
        await self._ensure_wiki_node(node_id)
        payload = business_material_payload(data)
        if "applicableTypes" in payload:
            payload["applicableTypes"] = [BUSINESS_BID_TYPE]
        return self._with_urls(await material_store.wiki_update(node_id, payload, BUSINESS_BID_TYPE))

    async def wiki_delete(self, node_id: str) -> dict[str, Any]:
        await self._ensure_wiki_node(node_id)
        return self._with_urls(await material_store.wiki_delete(node_id, BUSINESS_BID_TYPE))

    async def wiki_move(self, *, node_id: str, target_id: str, mode: str) -> dict[str, Any]:
        await self._ensure_wiki_node(node_id)
        await self._ensure_wiki_node(target_id, "目标 Wiki 节点")
        return self._with_urls(await material_store.wiki_move(
            node_id=node_id,
            target_id=target_id,
            mode=mode,
            bid_type=BUSINESS_BID_TYPE,
        ))

    async def wiki_upload_attachment(
        self,
        *,
        node_id: str,
        file_name: str,
        file_size: Any,
        upload: Any | None = None,
        data: bytes | None = None,
        mime_type: str = "",
    ) -> dict[str, Any]:
        await self._ensure_wiki_node(node_id)
        return self._with_urls(await material_store.wiki_upload_attachment(
            node_id=node_id,
            file_name=file_name,
            file_size=file_size,
            upload=upload,
            data=data,
            mime_type=mime_type,
            bid_type=BUSINESS_BID_TYPE,
        ))

    async def wiki_refresh_summary(self, node_id: str) -> dict[str, Any]:
        await self._ensure_wiki_node(node_id)
        return self._with_urls(await material_store.wiki_refresh_summary(node_id, BUSINESS_BID_TYPE))

    async def import_generated_wiki_blueprint(
        self,
        *,
        root_title: str,
        root_markdown_content: str = "",
        nodes: list[dict[str, Any]],
        mode: str = "create",
    ) -> dict[str, Any]:
        payload = await material_store.import_generated_wiki_blueprint(
            root_title=root_title,
            root_markdown_content=root_markdown_content,
            nodes=nodes,
            mode=mode,
            bid_type=BUSINESS_BID_TYPE,
        )
        selected_id = str((payload.get("selectedNode") or {}).get("id") or "")
        filtered = await self.wiki_list(selected_id)
        return {**filtered, "message": payload.get("message") or "商务标 Wiki 已生成。", "mode": payload.get("mode") or mode}

    async def wiki_download_attachment_content(self, attachment_id: str) -> dict[str, Any]:
        await self._ensure_wiki_attachment(attachment_id)
        return await material_store.wiki_download_attachment_content(attachment_id, BUSINESS_BID_TYPE)

    async def wiki_delete_attachment(self, attachment_id: str) -> dict[str, Any]:
        await self._ensure_wiki_attachment(attachment_id)
        return self._with_urls(await material_store.wiki_delete_attachment(attachment_id, BUSINESS_BID_TYPE))


business_material_store = BusinessMaterialStore()
