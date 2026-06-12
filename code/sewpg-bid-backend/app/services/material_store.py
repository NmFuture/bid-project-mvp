from __future__ import annotations

from functools import partial
from typing import Any

from app.models import async_session
from app.services.scoped_material_urls import INTERNAL_RAW_URL_PREFIX
from app.services.material_identity_options_operations import identity_options_operation
from app.services.material_raw_file_operations import raw_files_operation
from app.services.material_raw_folder_operations import RawFolderOperations
from app.services.material_raw_lifecycle_operations import (
    create_raw_folder,
    delete_raw_file,
    delete_raw_folder,
)
from app.services.material_raw_object_operations import (
    archive_raw_file_version,
    enqueue_cleaning_job,
    purge_raw_file_objects,
    raw_object_key,
    remove_cleaned_object_from_ext,
)
from app.services.material_raw_update_operations import update_raw_file
from app.services.material_raw_access_operations import (
    raw_cleaned_preview_operation,
    raw_download_cleaned_content_operation,
    raw_download_content_operation,
    raw_download_file_operation,
)
from app.services.material_runtime_tables import ensure_material_runtime_tables
from app.services.material_raw_tree_operations import raw_tree_operation
from app.services.material_upload_operations import upload_raw_files
from app.services.material_folder_scope import infer_material_tier_from_raw_folder
from app.services.material_move_operations import move_raw_file, move_raw_folder
from app.services.material_wiki_attachment_operations import (
    delete_wiki_attachment,
    download_wiki_attachment_content,
    upload_wiki_attachment,
)
from app.services.material_wiki_import_operations import import_generated_wiki_blueprint_operation
from app.services.material_wiki_list_operations import wiki_list_operation
from app.services.material_wiki_node_operations import (
    create_wiki_node,
    delete_wiki_node,
    move_wiki_node,
    refresh_wiki_summary,
    update_wiki_node,
)


class MaterialStore:
    """Real material store backed by PostgreSQL + MinIO.

    Drop-in replacement for ``PeripheralStore`` raw/wiki methods.
    """

    def __init__(self) -> None:
        self._raw_folders = RawFolderOperations(ensure_runtime_tables=ensure_material_runtime_tables)

    # ------------------------------------------------------------------ #
    # Raw Materials
    # ------------------------------------------------------------------ #

    async def raw_tree(self, *, bid_type: str) -> dict[str, Any]:
        return await raw_tree_operation(
            bid_type=bid_type,
            ensure_runtime_tables=ensure_material_runtime_tables,
            ensure_raw_material_roots=self._raw_folders.ensure_raw_material_roots,
            session_factory=async_session,
        )

    async def identity_options(self, *, bid_type: str) -> dict[str, Any]:
        return await identity_options_operation(
            bid_type=bid_type,
            ensure_runtime_tables=ensure_material_runtime_tables,
            ensure_raw_material_roots=self._raw_folders.ensure_raw_material_roots,
            session_factory=async_session,
        )

    async def raw_files(
        self,
        *,
        bid_type: str,
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
        return await raw_files_operation(
            folder_path=folder_path,
            project_id=project_id,
            customer_name=customer_name,
            bid_type=bid_type,
            material_tier=material_tier,
            clean_status=clean_status,
            business_material_kind=business_material_kind,
            tag=tag,
            title=title,
            keyword=keyword,
            recursive=recursive,
            page=page,
            page_size=page_size,
        )

    async def raw_bootstrap_folders(self, project_id: str, bid_type: str) -> dict[str, Any]:
        return await self._raw_folders.raw_bootstrap_folders(
            project_id=project_id,
            bid_type=bid_type,
            session_factory=async_session,
        )

    async def raw_create_folder(self, parent_path: str, folder_name: str, *, bid_type: str) -> dict[str, Any]:
        return await create_raw_folder(
            parent_path=parent_path,
            folder_name=folder_name,
            bid_type=bid_type,
            ensure_runtime_tables=ensure_material_runtime_tables,
            ensure_folder_path=self._raw_folders.ensure_folder_path,
            raw_tree=lambda: self.raw_tree(bid_type=bid_type),
        )

    async def raw_delete_folder(self, path: str, *, bid_type: str) -> dict[str, Any]:
        return await delete_raw_folder(
            path=path,
            bid_type=bid_type,
            ensure_runtime_tables=ensure_material_runtime_tables,
            purge_raw_file_objects=partial(
                purge_raw_file_objects,
                ensure_runtime_tables=ensure_material_runtime_tables,
            ),
            mark_default_folder_deleted=self._raw_folders.mark_default_folder_deleted,
            raw_tree=lambda: self.raw_tree(bid_type=bid_type),
        )

    async def raw_cleanup_project_folder(self, path: str, *, bid_type: str) -> dict[str, Any]:
        return await delete_raw_folder(
            path=path,
            bid_type=bid_type,
            ensure_runtime_tables=ensure_material_runtime_tables,
            purge_raw_file_objects=partial(
                purge_raw_file_objects,
                ensure_runtime_tables=ensure_material_runtime_tables,
            ),
            mark_default_folder_deleted=self._raw_folders.mark_default_folder_deleted,
            raw_tree=lambda: self.raw_tree(bid_type=bid_type),
            allow_protected=True,
        )

    async def raw_upload(
        self,
        *,
        target_path: str = "",
        project_id: str = "",
        project_code: str = "",
        project_name: str = "",
        bid_type: str,
        material_tier: str = "",
        business_material_kind: str = "",
        customer_id: str = "",
        customer_name: str = "",
        tags: Any = None,
        on_conflict: str = "",
        files: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return await upload_raw_files(
            target_path=target_path,
            project_id=project_id,
            project_code=project_code,
            project_name=project_name,
            customer_name=customer_name,
            bid_type=bid_type,
            material_tier=material_tier,
            business_material_kind=business_material_kind,
            customer_id=customer_id,
            tags=tags,
            on_conflict=on_conflict,
            files=list(files or []),
            ensure_runtime_tables=ensure_material_runtime_tables,
            ensure_folder_path=self._raw_folders.ensure_folder_path,
            clear_default_folder_deletion=self._raw_folders.clear_default_folder_deletion,
            ensure_nested_folder=self._raw_folders.ensure_nested_folder,
            archive_raw_file_version=partial(
                archive_raw_file_version,
                ensure_runtime_tables=ensure_material_runtime_tables,
            ),
            remove_cleaned_object_from_ext=remove_cleaned_object_from_ext,
            raw_object_key=raw_object_key,
            infer_material_tier_from_folder=infer_material_tier_from_raw_folder,
            enqueue_cleaning_job=enqueue_cleaning_job,
        )

    async def raw_update_file(
        self,
        file_id: str,
        *,
        bid_type: str,
        name: str = "",
        business_material_kind: str = "",
        tags: Any = None,
        update_tags: bool = False,
    ) -> dict[str, Any]:
        return await update_raw_file(
            file_id=file_id,
            bid_type=bid_type,
            name=name,
            business_material_kind=business_material_kind,
            tags=tags,
            update_tags=update_tags,
            ensure_runtime_tables=ensure_material_runtime_tables,
            raw_object_key=raw_object_key,
        )

    async def raw_delete_file(self, file_id: str, *, bid_type: str) -> dict[str, Any]:
        return await delete_raw_file(
            file_id=file_id,
            bid_type=bid_type,
            ensure_runtime_tables=ensure_material_runtime_tables,
            purge_raw_file_objects=partial(
                purge_raw_file_objects,
                ensure_runtime_tables=ensure_material_runtime_tables,
            ),
        )

    async def raw_download_file(self, file_id: str, *, bid_type: str) -> dict[str, Any]:
        return await raw_download_file_operation(
            file_id=file_id,
            bid_type=bid_type,
            ensure_runtime_tables=ensure_material_runtime_tables,
        )

    async def raw_download_content(self, file_id: str, *, bid_type: str) -> dict[str, Any]:
        return await raw_download_content_operation(
            file_id=file_id,
            bid_type=bid_type,
            ensure_runtime_tables=ensure_material_runtime_tables,
        )

    async def raw_cleaned_preview(
        self,
        file_id: str,
        *,
        bid_type: str,
        browser_base_url: str = "",
        onlyoffice_base_url: str = "",
        content_path_prefix: str = INTERNAL_RAW_URL_PREFIX,
    ) -> dict[str, Any]:
        return await raw_cleaned_preview_operation(
            file_id=file_id,
            bid_type=bid_type,
            browser_base_url=browser_base_url,
            onlyoffice_base_url=onlyoffice_base_url,
            content_path_prefix=content_path_prefix,
            ensure_runtime_tables=ensure_material_runtime_tables,
        )

    async def raw_download_cleaned_content(self, file_id: str, *, bid_type: str) -> dict[str, Any]:
        return await raw_download_cleaned_content_operation(
            file_id=file_id,
            bid_type=bid_type,
            ensure_runtime_tables=ensure_material_runtime_tables,
        )

    # ------------------------------------------------------------------ #
    # Wiki Materials
    # ------------------------------------------------------------------ #

    async def wiki_list(self, node_id: str, bid_type: str) -> dict[str, Any]:
        return await wiki_list_operation(
            node_id=node_id,
            bid_type=bid_type,
            ensure_runtime_tables=ensure_material_runtime_tables,
        )

    async def wiki_create(self, parent_id: str, title: str, is_folder: bool, bid_type: str) -> dict[str, Any]:
        return await create_wiki_node(
            parent_id=parent_id,
            title=title,
            is_folder=is_folder,
            bid_type=bid_type,
            ensure_runtime_tables=ensure_material_runtime_tables,
            wiki_list=self.wiki_list,
        )

    async def wiki_update(self, node_id: str, data: dict[str, Any], bid_type: str) -> dict[str, Any]:
        return await update_wiki_node(
            node_id=node_id,
            data=data,
            bid_type=bid_type,
            ensure_runtime_tables=ensure_material_runtime_tables,
            wiki_list=self.wiki_list,
        )

    async def wiki_delete(self, node_id: str, bid_type: str) -> dict[str, Any]:
        return await delete_wiki_node(
            node_id=node_id,
            bid_type=bid_type,
            ensure_runtime_tables=ensure_material_runtime_tables,
            wiki_list=self.wiki_list,
        )

    async def wiki_refresh_summary(self, node_id: str, bid_type: str) -> dict[str, Any]:
        return await refresh_wiki_summary(
            node_id=node_id,
            bid_type=bid_type,
            ensure_runtime_tables=ensure_material_runtime_tables,
            wiki_list=self.wiki_list,
        )

    async def wiki_move(self, node_id: str, target_id: str, mode: str, bid_type: str) -> dict[str, Any]:
        return await move_wiki_node(
            node_id=node_id,
            target_id=target_id,
            mode=mode,
            bid_type=bid_type,
            ensure_runtime_tables=ensure_material_runtime_tables,
            wiki_list=self.wiki_list,
        )

    async def wiki_upload_attachment(
        self,
        node_id: str,
        file_name: str,
        file_size: Any,
        *,
        upload: Any | None = None,
        data: bytes | None = None,
        mime_type: str = "",
        bid_type: str,
    ) -> dict[str, Any]:
        return await upload_wiki_attachment(
            node_id=node_id,
            file_name=file_name,
            file_size=file_size,
            upload=upload,
            data=data,
            mime_type=mime_type,
            bid_type=bid_type,
            ensure_runtime_tables=ensure_material_runtime_tables,
            wiki_list=self.wiki_list,
        )

    async def wiki_download_attachment_content(self, attachment_id: str, bid_type: str) -> dict[str, Any]:
        return await download_wiki_attachment_content(
            attachment_id=attachment_id,
            bid_type=bid_type,
            ensure_runtime_tables=ensure_material_runtime_tables,
        )

    async def wiki_delete_attachment(self, attachment_id: str, bid_type: str) -> dict[str, Any]:
        return await delete_wiki_attachment(
            attachment_id=attachment_id,
            bid_type=bid_type,
            ensure_runtime_tables=ensure_material_runtime_tables,
            wiki_list=self.wiki_list,
        )

    async def import_generated_wiki_blueprint(
        self,
        *,
        root_title: str,
        root_markdown_content: str = "",
        nodes: list[dict[str, Any]],
        mode: str = "create",
        bid_type: str,
    ) -> dict[str, Any]:
        return await import_generated_wiki_blueprint_operation(
            root_title=root_title,
            root_markdown_content=root_markdown_content,
            nodes=nodes,
            mode=mode,
            bid_type=bid_type,
            ensure_runtime_tables=ensure_material_runtime_tables,
            wiki_list=self.wiki_list,
        )

    async def raw_move_file(
        self,
        file_id: str,
        target_path: str,
        *,
        bid_type: str,
        on_conflict: str = "",
    ) -> dict[str, Any]:
        return await move_raw_file(
            file_id=file_id,
            target_path=target_path,
            bid_type=bid_type,
            on_conflict=on_conflict,
            ensure_runtime_tables=ensure_material_runtime_tables,
            raw_object_key=raw_object_key,
            purge_raw_file_objects=partial(
                purge_raw_file_objects,
                ensure_runtime_tables=ensure_material_runtime_tables,
            ),
            infer_material_tier_from_folder=infer_material_tier_from_raw_folder,
        )

    async def raw_move_folder(self, source_path: str, target_parent_path: str, *, bid_type: str) -> dict[str, Any]:
        return await move_raw_folder(
            source_path=source_path,
            target_parent_path=target_parent_path,
            bid_type=bid_type,
            ensure_runtime_tables=ensure_material_runtime_tables,
            raw_object_key=raw_object_key,
            infer_material_tier_from_folder=infer_material_tier_from_raw_folder,
            raw_tree=lambda: self.raw_tree(bid_type=bid_type),
        )


material_store = MaterialStore()
