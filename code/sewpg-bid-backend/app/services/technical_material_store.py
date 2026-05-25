from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import async_session
from app.models.materials import WikiAttachment
from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.material_store import material_store
from app.services.peripheral import PeripheralError
from app.services.scoped_material_urls import rewrite_material_urls
from app.services.technical_turbine_material_options import list_technical_turbine_model_options
from app.services.turbine_models import material_model_fit, normalize_project_turbine_model


def normalize_technical_material_path(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/")


def ensure_technical_material_path(path: str, label: str = "路径") -> str:
    normalized = normalize_technical_material_path(path)
    if normalized and normalized != TECHNICAL_BID_TYPE and not normalized.startswith(f"{TECHNICAL_BID_TYPE}/"):
        raise PeripheralError(400, f"{label}必须位于技术标素材库。", "TECHNICAL_MATERIAL_PATH_REQUIRED")
    return normalized


def technical_material_payload(data: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(data or {})
    payload["bidType"] = TECHNICAL_BID_TYPE
    return payload


def _technical_tree(payload: dict[str, Any]) -> dict[str, Any]:
    tree = [
        item
        for item in (payload.get("tree") or [])
        if normalize_technical_material_path(str(item.get("path") or item.get("name") or "")) == TECHNICAL_BID_TYPE
    ]
    return {**payload, "tree": tree}


def _force_technical_tree(payload: dict[str, Any]) -> dict[str, Any]:
    if "tree" not in payload:
        return payload
    return _technical_tree(payload)


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


class TechnicalMaterialStore:
    @staticmethod
    def _with_urls(payload: Any) -> Any:
        return rewrite_material_urls(
            payload,
            raw_prefix="/api/technical/materials/raw",
            wiki_prefix="/api/technical/materials/wiki",
        )

    def ensure_path(self, path: str, label: str = "路径") -> str:
        return ensure_technical_material_path(path, label)

    def ensure_root_path(self, path: str, label: str = "路径") -> str:
        normalized = self.ensure_path(path, label)
        return normalized if normalized else TECHNICAL_BID_TYPE

    def ensure_parent_path(self, path: str, label: str = "父级目录") -> str:
        return self.ensure_root_path(path, label)

    async def ensure_raw_file(self, file_id: str) -> None:
        payload = await material_store.raw_files(
            bid_type=TECHNICAL_BID_TYPE,
            folder_path=TECHNICAL_BID_TYPE,
            recursive=True,
            page=1,
            page_size=100000,
        )
        if not any(str(item.get("id") or "") == file_id for item in payload.get("items") or []):
            raise PeripheralError(400, "该文件不属于技术标素材库。", "TECHNICAL_RAW_FILE_SCOPE")

    async def _ensure_wiki_node(self, node_id: str, label: str = "Wiki 节点") -> None:
        if not node_id:
            return
        payload = await material_store.wiki_list("", TECHNICAL_BID_TYPE)
        if node_id not in _collect_wiki_ids(list(payload.get("tree") or [])):
            raise PeripheralError(400, f"{label}不属于技术标 Wiki。", "TECHNICAL_WIKI_NODE_SCOPE")

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
        return await material_store.identity_options(bid_type=TECHNICAL_BID_TYPE)

    async def turbine_model_options(self) -> dict[str, Any]:
        return await list_technical_turbine_model_options()

    async def raw_tree(self) -> dict[str, Any]:
        return self._with_urls(_technical_tree(await material_store.raw_tree(bid_type=TECHNICAL_BID_TYPE)))

    async def raw_files(
        self,
        *,
        folder_path: str = "",
        project_id: str = "",
        customer_name: str = "",
        material_tier: str = "",
        clean_status: str = "",
        keyword: str = "",
        turbine_model: dict[str, Any] | str | None = None,
        recursive: bool = True,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        selected_turbine = normalize_project_turbine_model(turbine_model)
        base_payload = await material_store.raw_files(
            bid_type=TECHNICAL_BID_TYPE,
            folder_path=self.ensure_root_path(folder_path, "素材目录"),
            project_id=project_id,
            customer_name=customer_name,
            material_tier=material_tier,
            clean_status=clean_status,
            keyword=keyword,
            recursive=recursive,
            page=1 if selected_turbine else page,
            page_size=100000 if selected_turbine else page_size,
        )
        if not selected_turbine:
            return self._with_urls(base_payload)

        filtered = []
        for item in base_payload.get("items") or []:
            fit = material_model_fit(item, selected_turbine)
            if fit != "conflict":
                filtered.append(item)
        filtered.sort(key=lambda item: 0 if material_model_fit(item, selected_turbine) == "match" else 1)
        total = len(filtered)
        start = max(0, (page - 1) * page_size)
        end = start + page_size
        return self._with_urls(
            {
                **base_payload,
                "items": filtered[start:end],
                "total": total,
                "page": page,
                "pageSize": page_size,
            }
        )

    async def raw_bootstrap_folders(self, project_id: str) -> dict[str, Any]:
        return self._with_urls(await material_store.raw_bootstrap_folders(
            project_id=project_id,
            bid_type=TECHNICAL_BID_TYPE,
        ))

    async def raw_create_folder(self, parent_path: str, folder_name: str) -> dict[str, Any]:
        payload = await material_store.raw_create_folder(
            parent_path=self.ensure_parent_path(parent_path, "父级目录"),
            folder_name=folder_name,
            bid_type=TECHNICAL_BID_TYPE,
        )
        return self._with_urls(_force_technical_tree(payload))

    async def raw_delete_folder(self, path: str) -> dict[str, Any]:
        payload = await material_store.raw_delete_folder(
            self.ensure_path(path, "目标目录"),
            bid_type=TECHNICAL_BID_TYPE,
        )
        return self._with_urls(_force_technical_tree(payload))

    async def raw_upload(
        self,
        *,
        target_path: str = "",
        project_id: str = "",
        project_code: str = "",
        project_name: str = "",
        material_tier: str = "",
        customer_id: str = "",
        customer_name: str = "",
        on_conflict: str = "",
        files: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return self._with_urls(await material_store.raw_upload(
            target_path=self.ensure_path(target_path, "目标目录"),
            project_id=project_id,
            project_code=project_code,
            project_name=project_name,
            bid_type=TECHNICAL_BID_TYPE,
            material_tier=material_tier,
            customer_id=customer_id,
            customer_name=customer_name,
            on_conflict=on_conflict,
            files=list(files or []),
        ))

    async def raw_update_file(self, file_id: str, *, name: str = "") -> dict[str, Any]:
        await self.ensure_raw_file(file_id)
        return self._with_urls(await material_store.raw_update_file(
            file_id=file_id,
            bid_type=TECHNICAL_BID_TYPE,
            name=name,
        ))

    async def raw_move_file(self, *, file_id: str, target_path: str, on_conflict: str = "") -> dict[str, Any]:
        await self.ensure_raw_file(file_id)
        return self._with_urls(await material_store.raw_move_file(
            file_id=file_id,
            target_path=self.ensure_path(target_path, "目标目录"),
            bid_type=TECHNICAL_BID_TYPE,
            on_conflict=on_conflict,
        ))

    async def raw_move_folder(self, *, source_path: str, target_parent_path: str) -> dict[str, Any]:
        payload = await material_store.raw_move_folder(
            source_path=self.ensure_path(source_path, "源目录"),
            target_parent_path=self.ensure_parent_path(target_parent_path, "目标父级目录"),
            bid_type=TECHNICAL_BID_TYPE,
        )
        return self._with_urls(_force_technical_tree(payload))

    async def raw_delete_file(self, file_id: str) -> dict[str, Any]:
        await self.ensure_raw_file(file_id)
        return self._with_urls(await material_store.raw_delete_file(file_id, bid_type=TECHNICAL_BID_TYPE))

    async def raw_download_file(self, file_id: str) -> dict[str, Any]:
        await self.ensure_raw_file(file_id)
        return self._with_urls(await material_store.raw_download_file(file_id, bid_type=TECHNICAL_BID_TYPE))

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
            bid_type=TECHNICAL_BID_TYPE,
            browser_base_url=browser_base_url,
            onlyoffice_base_url=onlyoffice_base_url,
            content_path_prefix="/api/technical/materials/raw",
        )

    async def raw_download_cleaned_content(self, file_id: str) -> dict[str, Any]:
        await self.ensure_raw_file(file_id)
        return await material_store.raw_download_cleaned_content(file_id, bid_type=TECHNICAL_BID_TYPE)

    async def raw_download_content(self, file_id: str) -> dict[str, Any]:
        await self.ensure_raw_file(file_id)
        return await material_store.raw_download_content(file_id, bid_type=TECHNICAL_BID_TYPE)

    async def wiki_list(self, node_id: str = "") -> dict[str, Any]:
        return self._with_urls(await material_store.wiki_list(node_id, TECHNICAL_BID_TYPE))

    async def wiki_create(self, *, parent_id: str, title: str, is_folder: bool) -> dict[str, Any]:
        await self._ensure_wiki_node(parent_id, "父级 Wiki 节点")
        return self._with_urls(await material_store.wiki_create(
            parent_id=parent_id,
            title=title,
            is_folder=is_folder,
            bid_type=TECHNICAL_BID_TYPE,
        ))

    async def wiki_update(self, node_id: str, data: dict[str, Any]) -> dict[str, Any]:
        await self._ensure_wiki_node(node_id)
        payload = technical_material_payload(data)
        if "applicableTypes" in payload:
            payload["applicableTypes"] = [TECHNICAL_BID_TYPE]
        return self._with_urls(await material_store.wiki_update(node_id, payload, TECHNICAL_BID_TYPE))

    async def wiki_delete(self, node_id: str) -> dict[str, Any]:
        await self._ensure_wiki_node(node_id)
        return self._with_urls(await material_store.wiki_delete(node_id, TECHNICAL_BID_TYPE))

    async def wiki_move(self, *, node_id: str, target_id: str, mode: str) -> dict[str, Any]:
        await self._ensure_wiki_node(node_id)
        await self._ensure_wiki_node(target_id, "目标 Wiki 节点")
        return self._with_urls(await material_store.wiki_move(
            node_id=node_id,
            target_id=target_id,
            mode=mode,
            bid_type=TECHNICAL_BID_TYPE,
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
            bid_type=TECHNICAL_BID_TYPE,
        ))

    async def wiki_refresh_summary(self, node_id: str) -> dict[str, Any]:
        await self._ensure_wiki_node(node_id)
        return self._with_urls(await material_store.wiki_refresh_summary(node_id, TECHNICAL_BID_TYPE))

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
            bid_type=TECHNICAL_BID_TYPE,
        )
        selected_id = str((payload.get("selectedNode") or {}).get("id") or "")
        filtered = await self.wiki_list(selected_id)
        return {**filtered, "message": payload.get("message") or "技术标 Wiki 已生成。", "mode": payload.get("mode") or mode}

    async def wiki_download_attachment_content(self, attachment_id: str) -> dict[str, Any]:
        await self._ensure_wiki_attachment(attachment_id)
        return await material_store.wiki_download_attachment_content(attachment_id, TECHNICAL_BID_TYPE)

    async def wiki_delete_attachment(self, attachment_id: str) -> dict[str, Any]:
        await self._ensure_wiki_attachment(attachment_id)
        return self._with_urls(await material_store.wiki_delete_attachment(attachment_id, TECHNICAL_BID_TYPE))


technical_material_store = TechnicalMaterialStore()
