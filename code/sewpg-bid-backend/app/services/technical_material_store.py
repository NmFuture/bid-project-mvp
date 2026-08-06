from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import async_session
from app.models.materials import RawFolder, WikiAttachment
from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.business_material_splitter import (
    confirm_business_material_split,
    preview_business_material_split,
)
from app.services.material_store import material_store
from app.services.material_certificate_time import (
    delete_certificate_time_record,
    delete_certificate_time_records,
    list_certificate_time_registry,
    run_certificate_time_batch,
    run_certificate_time_incremental,
    suggest_certificate_time_scopes,
    update_certificate_time_scopes,
    update_certificate_time_record,
)
from app.services.material_auto_tags import build_auto_tag_items
from app.services.material_tags import GENERIC_MODEL_TAG
from app.services.material_tag_import import build_preview, parse_tag_excel, same_name_file_ids
from app.services.material_tag_import_fuzzy import run_tag_import_fuzzy_match
from app.services.peripheral import PeripheralError
from app.services.scoped_material_urls import rewrite_material_urls
from app.services.technical_material_paths import (
    TECHNICAL_STANDARD_FOLDER_NAME,
    canonical_technical_material_child_name,
    ensure_technical_material_new_child_path,
    ensure_technical_material_path,
    ensure_technical_material_write_path,
    normalize_technical_material_path,
)
from app.services.technical_turbine_material_options import list_technical_turbine_model_options
from app.services.turbine_models import is_valid_turbine_model, material_model_fit, normalize_project_turbine_model

logger = logging.getLogger(__name__)


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

    async def _refresh_index(self, payload: Any) -> Any:
        """改结构操作后 best-effort 重建技术标三级目录 JSON 索引。

        延迟导入避免循环引用；rebuild 内部已做异常隔离，这里再兜底一层。
        """
        from app.services.technical_material_index import rebuild_technical_material_index

        try:
            await rebuild_technical_material_index()
        except Exception:  # noqa: BLE001 - 钩子不得阻断主素材操作
            logger.warning("technical material index refresh failed", exc_info=True)
        return payload

    def ensure_path(self, path: str, label: str = "路径") -> str:
        return ensure_technical_material_path(path, label)

    def ensure_root_path(self, path: str, label: str = "路径") -> str:
        normalized = self.ensure_path(path, label)
        return normalized if normalized else TECHNICAL_BID_TYPE

    def ensure_parent_path(self, path: str, label: str = "父级目录") -> str:
        return self.ensure_root_path(path, label)

    def ensure_write_path(self, path: str, label: str = "目标目录", *, allow_root: bool = False) -> str:
        return ensure_technical_material_write_path(path, label, allow_root=allow_root)

    def ensure_new_child_parent_path(self, parent_path: str, folder_name: str, label: str = "父级目录") -> str:
        return ensure_technical_material_new_child_path(parent_path, folder_name, label)

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

    async def raw_project_folder_owner(self, path: str) -> str:
        normalized = self.ensure_path(path, "项目素材目录")
        parts = [part for part in normalized.split("/") if part]
        if len(parts) != 3 or parts[:2] != [TECHNICAL_BID_TYPE, "项目定制"]:
            raise PeripheralError(400, "只能查询技术标项目定制目录。", "PROJECT_MATERIAL_PATH_REQUIRED")
        async with async_session() as session:
            result = await session.execute(select(RawFolder.project_id).where(RawFolder.path == normalized))
            project_id = result.scalar_one_or_none()
        if project_id is None:
            raise PeripheralError(404, "项目素材目录不存在。", "RAW_FOLDER_NOT_FOUND")
        return str(project_id or "").strip()

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
        title: str = "",
        tag: Any = None,
        recursive: bool = True,
        page: int = 1,
        page_size: int = 20,
        use_index_tags: bool = True,
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
            title=title,
            tag=[] if use_index_tags else (tag or []),
            recursive=recursive,
            page=1 if (selected_turbine or use_index_tags) else page,
            page_size=100000 if (selected_turbine or use_index_tags) else page_size,
        )
        if use_index_tags:
            base_payload = await self._with_current_index_tags(base_payload)
        selected_tags = self._normalize_tags(tag)

        filtered = []
        for item in base_payload.get("items") or []:
            if selected_tags and not self._item_matches_tags(item, selected_tags):
                continue
            fit = material_model_fit(item, selected_turbine) if selected_turbine else ""
            if not selected_turbine or fit != "conflict":
                filtered.append(item)
        if selected_turbine:
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
                "tagOptions": self._tag_options(base_payload.get("items") or []),
            }
        )

    async def _with_current_index_tags(self, payload: dict[str, Any]) -> dict[str, Any]:
        from app.services.technical_material_index import load_technical_material_index, rebuild_technical_material_index

        index_payload = load_technical_material_index()
        if not index_payload:
            index_payload = await rebuild_technical_material_index()
        return self._with_index_tags(payload, index_payload=index_payload)

    def _with_index_tags(self, payload: dict[str, Any], *, index_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        from app.services.technical_material_index import file_tags_by_id

        tags_by_id = file_tags_by_id(index_payload)
        items = []
        for item in payload.get("items") or []:
            item_id = str(item.get("id") or "")
            items.append({**item, "tags": tags_by_id.get(item_id, [])})
        return {**payload, "items": items, "tagOptions": self._tag_options(items)}

    @staticmethod
    def _normalize_tags(value: Any) -> list[str]:
        from app.services.material_tags import normalize_material_tags

        return normalize_material_tags(value)

    @classmethod
    def _item_matches_tags(cls, item: dict[str, Any], requested_tags: list[str]) -> bool:
        tags = cls._normalize_tags(item.get("tags"))
        return all(cls._requested_tag_hit(tags, requested_tag) for requested_tag in requested_tags)

    @staticmethod
    def _requested_tag_hit(tags: list[str], requested_tag: str) -> bool:
        if any(requested_tag in tag for tag in tags):
            return True
        # 跨机型复用（R06-B06-02）：带「通用」标签的素材可被任意具体机型标签命中；
        # 非机型标签（部件/认证证书等）维持原有子串匹配，不受影响。
        return is_valid_turbine_model(requested_tag) and GENERIC_MODEL_TAG in tags

    @classmethod
    def _tag_options(cls, items: list[dict[str, Any]]) -> list[str]:
        seen: set[str] = set()
        options: list[str] = []
        for item in items:
            for tag in cls._normalize_tags(item.get("tags")):
                key = tag.casefold()
                if key in seen:
                    continue
                seen.add(key)
                options.append(tag)
        return options

    async def raw_bootstrap_folders(self, project_id: str) -> dict[str, Any]:
        return await self._refresh_index(self._with_urls(await material_store.raw_bootstrap_folders(
            project_id=project_id,
            bid_type=TECHNICAL_BID_TYPE,
        )))

    async def raw_create_folder(self, parent_path: str, folder_name: str) -> dict[str, Any]:
        normalized_parent_path = self.ensure_new_child_parent_path(parent_path, folder_name, "父级目录")
        payload = await material_store.raw_create_folder(
            parent_path=normalized_parent_path,
            folder_name=canonical_technical_material_child_name(normalized_parent_path, folder_name),
            bid_type=TECHNICAL_BID_TYPE,
        )
        return await self._refresh_index(self._with_urls(_force_technical_tree(payload)))

    async def raw_delete_folder(self, path: str) -> dict[str, Any]:
        payload = await material_store.raw_delete_folder(
            self.ensure_path(path, "目标目录"),
            bid_type=TECHNICAL_BID_TYPE,
        )
        return await self._refresh_index(self._with_urls(_force_technical_tree(payload)))

    async def raw_rename_folder(self, *, path: str, new_name: str) -> dict[str, Any]:
        payload = await material_store.raw_rename_folder(
            self.ensure_path(path, "目标目录"),
            new_name,
            bid_type=TECHNICAL_BID_TYPE,
        )
        return await self._refresh_index(self._with_urls(_force_technical_tree(payload)))

    async def raw_migrate_project_folder(self, *, path: str, new_name: str) -> dict[str, Any]:
        normalized = self.ensure_path(path, "旧项目素材目录")
        parts = [part for part in normalized.split("/") if part]
        if len(parts) != 3 or parts[:2] != [TECHNICAL_BID_TYPE, "项目定制"]:
            raise PeripheralError(400, "只能迁移技术标项目定制目录。", "PROJECT_MATERIAL_PATH_REQUIRED")
        payload = await material_store.raw_rename_folder(
            normalized,
            new_name,
            bid_type=TECHNICAL_BID_TYPE,
            allow_identity_folder=True,
        )
        return await self._refresh_index(self._with_urls(_force_technical_tree(payload)))

    async def raw_cleanup_project_folder(self, path: str, *, expected_project_id: str = "") -> dict[str, Any]:
        normalized = self.ensure_path(path, "项目素材目录")
        parts = [part for part in normalized.split("/") if part]
        if len(parts) != 3 or parts[0] != TECHNICAL_BID_TYPE or parts[1] not in {"项目定制", "项目素材"}:
            raise PeripheralError(400, "只能清理技术标项目素材目录。", "PROJECT_MATERIAL_PATH_REQUIRED")
        cleanup_kwargs = {"bid_type": TECHNICAL_BID_TYPE}
        if expected_project_id:
            cleanup_kwargs["expected_project_id"] = expected_project_id
        payload = await material_store.raw_cleanup_project_folder(normalized, **cleanup_kwargs)
        return await self._refresh_index(self._with_urls(_force_technical_tree(payload)))

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
        tags: Any = None,
        on_conflict: str = "",
        files: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        normalized_target_path = self.ensure_path(target_path, "目标目录") if target_path else ""
        normalized_material_tier = str(material_tier or "").strip()
        if not normalized_target_path and not normalized_material_tier:
            normalized_target_path = f"{TECHNICAL_BID_TYPE}/{TECHNICAL_STANDARD_FOLDER_NAME}"
        payload = self._with_urls(await material_store.raw_upload(
            target_path=normalized_target_path,
            project_id=project_id,
            project_code=project_code,
            project_name=project_name,
            bid_type=TECHNICAL_BID_TYPE,
            material_tier=normalized_material_tier,
            customer_id=customer_id,
            customer_name=customer_name,
            tags=tags,
            on_conflict=on_conflict,
            files=list(files or []),
        ))
        await self._refresh_index(payload)
        upload_tags = self._normalize_tags(tags)
        if upload_tags:
            tag_sync_failed_ids: set[str] = set()
            for item in payload.get("items") or []:
                item_id = str(item.get("id") or "")
                if item_id:
                    try:
                        await self.set_index_tags(item_id, upload_tags)
                    except LookupError:
                        tag_sync_failed_ids.add(item_id)
                        logger.warning("technical upload tag sync skipped; node not in index: %s", item_id)
            payload = await self._with_current_index_tags(payload)
            if tag_sync_failed_ids:
                items = []
                for item in payload.get("items") or []:
                    item_id = str(item.get("id") or "")
                    items.append({**item, "tags": upload_tags} if item_id in tag_sync_failed_ids else item)
                payload = {**payload, "items": items, "tagOptions": self._tag_options(items)}
        return payload

    async def raw_update_file(
        self,
        file_id: str,
        *,
        name: str = "",
        business_material_kind: str = "",
        tags: Any = None,
        update_tags: bool = False,
        tag_mode: str = "overwrite",
    ) -> dict[str, Any]:
        await self.ensure_raw_file(file_id)
        payload = await self._refresh_index(self._with_urls(await material_store.raw_update_file(
            file_id=file_id,
            bid_type=TECHNICAL_BID_TYPE,
            name=name,
            business_material_kind=business_material_kind,
            tags=None,
            update_tags=False,
        )))
        if update_tags:
            final_tags = tags
            if tag_mode == "append":
                current_payload = await self._with_current_index_tags({"items": [{"id": file_id}]})
                current_tags = (current_payload.get("items") or [{}])[0].get("tags") or []
                from app.services.material_tags import normalize_material_tags
                final_tags = normalize_material_tags(list(current_tags) + list(normalize_material_tags(tags)))
            node = await self.set_index_tags(file_id, final_tags)
            item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
            payload["item"] = {**item, "tags": node.get("tags") or []}
        return payload

    async def _raw_subtree_files(self, target_path: str) -> list[dict[str, Any]]:
        payload = await material_store.raw_files(
            bid_type=TECHNICAL_BID_TYPE,
            folder_path=target_path or TECHNICAL_BID_TYPE,
            recursive=True,
            page=1,
            page_size=100000,
        )
        return list(payload.get("items") or [])

    async def raw_tag_import_preview(
        self,
        *,
        target_path: str,
        file_bytes: bytes,
        use_fuzzy: bool = False,
        import_mode: str = "merge",
    ) -> dict[str, Any]:
        mode = "overwrite" if import_mode == "overwrite" else "merge"
        normalized_target = self.ensure_root_path(target_path, "目标目录")
        rows = parse_tag_excel(file_bytes)
        files = await self._raw_subtree_files(normalized_target)
        files = (await self._with_current_index_tags({"items": files})).get("items") or []
        preview = build_preview(rows, files, mode=mode)
        preview["targetPath"] = normalized_target
        preview["importMode"] = mode
        preview["fuzzyAvailable"] = False
        if use_fuzzy and preview.get("unmatched"):
            preview = await self._augment_with_fuzzy(preview, files, mode=mode)
        return preview

    async def _augment_with_fuzzy(
        self,
        preview: dict[str, Any],
        files: list[dict[str, Any]],
        *,
        mode: str = "merge",
    ) -> dict[str, Any]:
        """对 unmatched 行调用 opencode 模糊匹配 skill；失败则降级不阻断。"""

        try:
            fuzzy = await run_tag_import_fuzzy_match(
                unmatched=preview.get("unmatched") or [],
                candidates=files,
                mode=mode,
            )
        except Exception as exc:  # pragma: no cover - 降级路径
            preview["fuzzyAvailable"] = False
            preview["fuzzyError"] = str(exc)
            return preview

        preview["fuzzy"] = fuzzy or []
        preview["fuzzyAvailable"] = True
        return preview

    async def raw_tag_import_commit(
        self,
        *,
        items: list[dict[str, Any]],
        target_path: str = "",
        import_mode: str = "merge",
    ) -> dict[str, Any]:
        merge_tags = str(import_mode or "").strip().lower() != "overwrite"
        succeeded: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        # applyToAllMatches 行需要按目标子树解析同名文件；惰性加载，避免普通导入多扫一次库
        subtree_files: list[dict[str, Any]] | None = None
        for item in items or []:
            file_id = str(item.get("fileId") or "")
            tags = item.get("tags")
            if item.get("applyToAllMatches"):
                # 跨机型批量应用：该行标签写入目标子树内所有同名文件（含原选定文件）
                file_name = str(item.get("fileName") or "")
                if subtree_files is None:
                    normalized_target = self.ensure_root_path(target_path, "目标目录")
                    subtree_files = await self._raw_subtree_files(normalized_target)
                target_ids = same_name_file_ids(subtree_files, file_name)
                if not target_ids:
                    failed.append({"fileId": file_id, "fileName": file_name, "message": "目标目录内未找到同名文件。"})
                    continue
            elif file_id:
                target_ids = [file_id]
            else:
                failed.append({"fileId": file_id, "message": "缺少文件 ID。"})
                continue
            for target_id in target_ids:
                try:
                    # overwrite 模式走 merge=False，用 preview 给出的 mergedTags 替换当前真值
                    updated = await self.set_index_tags(target_id, tags, merge=merge_tags)
                    succeeded.append(
                        {
                            "fileId": target_id,
                            "name": str(updated.get("name") or ""),
                            "tags": updated.get("tags") or [],
                        }
                    )
                except PeripheralError as exc:
                    failed.append({"fileId": target_id, "message": exc.detail})
                except Exception as exc:  # pragma: no cover - 兜底
                    failed.append({"fileId": target_id, "message": str(exc)})
        message = f"标签导入完成：成功 {len(succeeded)} 个" + (
            f"，失败 {len(failed)} 个" if failed else ""
        )
        return {"message": message, "succeeded": succeeded, "failed": failed}

    async def raw_auto_tag_apply(self, *, target_path: str) -> dict[str, Any]:
        """一键自动打标签：按目录结构（机型/类别/子类）推导标签并合并写入。

        幂等：推导标签已全部存在的文件计入 unchanged 跳过；只增不删（merge）。
        """

        normalized_target = self.ensure_root_path(target_path, "目标目录")
        files = await self._raw_subtree_files(normalized_target)
        files = (await self._with_current_index_tags({"items": files})).get("items") or []
        items = build_auto_tag_items(files)

        succeeded: list[dict[str, Any]] = []
        unchanged: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for item in items:
            derived = list(item.get("tags") or [])
            existing = {str(tag).casefold() for tag in (item.get("existingTags") or [])}
            if derived and all(str(tag).casefold() in existing for tag in derived):
                unchanged.append({"fileId": item["fileId"], "name": item.get("name") or ""})
                continue
            try:
                updated = await self.set_index_tags(item["fileId"], derived, merge=True)
                succeeded.append(
                    {
                        "fileId": item["fileId"],
                        "name": str(updated.get("name") or ""),
                        "tags": updated.get("tags") or [],
                    }
                )
            except PeripheralError as exc:
                failed.append({"fileId": item["fileId"], "name": item.get("name") or "", "message": exc.detail})
            except Exception as exc:  # pragma: no cover - 兜底
                failed.append({"fileId": item["fileId"], "name": item.get("name") or "", "message": str(exc)})
        skipped = len(files) - len(items)
        message = f"自动打标签完成：更新 {len(succeeded)} 个，已是最新 {len(unchanged)} 个"
        if skipped:
            message += f"，无法推导标签跳过 {skipped} 个"
        if failed:
            message += f"，失败 {len(failed)} 个"
        return {
            "message": message,
            "targetPath": normalized_target,
            "succeeded": succeeded,
            "unchanged": unchanged,
            "failed": failed,
            "total": len(files),
        }

    async def set_index_tags(self, target_id: str, tags: Any, *, merge: bool = False) -> dict[str, Any]:
        from app.services.technical_material_index import set_tags_for_node

        return await set_tags_for_node(target_id=target_id, tags=tags, merge=merge)

    async def preview_technical_split(self, file_id: str, *, target_path: str, ai_mode: str) -> dict[str, Any]:
        await self.ensure_raw_file(file_id)
        return await preview_business_material_split(
            file_id=file_id,
            target_path=self.ensure_write_path(target_path, "目标目录"),
            ai_mode=ai_mode,
            bid_type=TECHNICAL_BID_TYPE,
        )

    async def confirm_technical_split(
        self,
        file_id: str,
        *,
        fragments: list[dict[str, Any]],
        target_path: str = "",
        on_conflict: str = "",
    ) -> dict[str, Any]:
        await self.ensure_raw_file(file_id)
        return await self._refresh_index(await confirm_business_material_split(
            file_id=file_id,
            fragments=fragments,
            default_target_path=self.ensure_write_path(target_path, "目标目录"),
            on_conflict=on_conflict,
            bid_type=TECHNICAL_BID_TYPE,
        ))

    async def preview_business_split(self, file_id: str, *, target_path: str, ai_mode: str) -> dict[str, Any]:
        return await self.preview_technical_split(file_id, target_path=target_path, ai_mode=ai_mode)

    async def confirm_business_split(
        self,
        file_id: str,
        *,
        fragments: list[dict[str, Any]],
        target_path: str = "",
        on_conflict: str = "",
    ) -> dict[str, Any]:
        return await self.confirm_technical_split(
            file_id,
            fragments=fragments,
            target_path=target_path,
            on_conflict=on_conflict,
        )

    async def raw_move_file(self, *, file_id: str, target_path: str, on_conflict: str = "") -> dict[str, Any]:
        await self.ensure_raw_file(file_id)
        return await self._refresh_index(self._with_urls(await material_store.raw_move_file(
            file_id=file_id,
            target_path=self.ensure_write_path(target_path, "目标目录"),
            bid_type=TECHNICAL_BID_TYPE,
            on_conflict=on_conflict,
        )))

    async def raw_batch_move_files(
        self,
        *,
        file_ids: list[str],
        target_path: str,
        on_conflict: str = "",
    ) -> dict[str, Any]:
        normalized_target = self.ensure_write_path(target_path, "目标目录")
        succeeded: list[str] = []
        failed: list[dict[str, str]] = []
        for file_id in dict.fromkeys(str(item or "").strip() for item in file_ids):
            if not file_id:
                continue
            try:
                await material_store.raw_move_file(
                    file_id=file_id,
                    target_path=normalized_target,
                    bid_type=TECHNICAL_BID_TYPE,
                    on_conflict=on_conflict,
                )
                succeeded.append(file_id)
            except PeripheralError as exc:
                failed.append({"fileId": file_id, "message": exc.detail})
        await self._refresh_index({})
        return {"succeeded": succeeded, "failed": failed, "targetPath": normalized_target}

    async def raw_move_folder(self, *, source_path: str, target_parent_path: str) -> dict[str, Any]:
        normalized_source = self.ensure_path(source_path, "源目录")
        normalized_target_parent = self.ensure_parent_path(target_parent_path, "目标父级目录")
        source_name = normalized_source.split("/")[-1] if normalized_source else ""
        target_path = "/".join(part for part in [normalized_target_parent, source_name] if part)
        self.ensure_write_path(target_path, "目标目录")
        payload = await material_store.raw_move_folder(
            source_path=normalized_source,
            target_parent_path=normalized_target_parent,
            bid_type=TECHNICAL_BID_TYPE,
        )
        return await self._refresh_index(self._with_urls(_force_technical_tree(payload)))

    async def raw_delete_file(self, file_id: str) -> dict[str, Any]:
        await self.ensure_raw_file(file_id)
        return await self._refresh_index(self._with_urls(await material_store.raw_delete_file(file_id, bid_type=TECHNICAL_BID_TYPE)))

    async def raw_batch_delete_files(self, file_ids: list[str]) -> dict[str, Any]:
        """批量删除素材文件：逐个删除但只在最后统一重建一次索引，避免 gather 并发 rebuild（H5）。"""
        succeeded: list[str] = []
        failed: list[dict[str, Any]] = []
        for fid in file_ids:
            try:
                await self.ensure_raw_file(fid)
                await material_store.raw_delete_file(fid, bid_type=TECHNICAL_BID_TYPE)
                succeeded.append(fid)
            except PeripheralError as exc:
                failed.append({"fileId": fid, "error": exc.detail})
            except Exception as exc:  # pragma: no cover - 兜底
                failed.append({"fileId": fid, "error": str(exc)})
        if succeeded:
            await self._refresh_index(None)
        total = len(file_ids)
        return {
            "succeeded": succeeded,
            "failed": failed,
            "message": f"批量删除完成：成功 {len(succeeded)} 个，失败 {total - len(succeeded)} 个",
        }

    async def raw_batch_tags(self, file_ids: list[str], *, tags: Any, tag_mode: str = "overwrite") -> dict[str, Any]:
        """批量打标签：逐个更新，只在最后统一重建一次索引，避免 gather 并发 rebuild（H5）。"""
        succeeded: list[str] = []
        failed: list[dict[str, Any]] = []
        for fid in file_ids:
            try:
                # 直接走索引 tag 更新，跳过每次 rebuild；append 语义在 set_index_tags 内合并
                if tag_mode == "append":
                    await self.set_index_tags(fid, tags, merge=True)
                else:
                    await self.set_index_tags(fid, tags)
                succeeded.append(fid)
            except PeripheralError as exc:
                failed.append({"fileId": fid, "error": exc.detail})
            except Exception as exc:  # pragma: no cover - 兜底
                failed.append({"fileId": fid, "error": str(exc)})
        if succeeded:
            await self._refresh_index(None)
        total = len(file_ids)
        return {
            "succeeded": succeeded,
            "failed": failed,
            "message": f"批量打标签完成：成功 {len(succeeded)} 个，失败 {total - len(succeeded)} 个",
        }

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

    async def raw_original_preview(
        self,
        file_id: str,
        *,
        browser_base_url: str = "",
        onlyoffice_base_url: str = "",
    ) -> dict[str, Any]:
        await self.ensure_raw_file(file_id)
        return await material_store.raw_original_preview(
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

    async def raw_certificate_time_batch(
        self,
        *,
        folder_path: str = "",
        file_ids: list[str] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        normalized_folder = self.ensure_root_path(folder_path, "证书目录") if folder_path else TECHNICAL_BID_TYPE
        return await run_certificate_time_batch(
            bid_type=TECHNICAL_BID_TYPE,
            folder_path=normalized_folder,
            file_ids=file_ids,
            limit=limit,
        )

    async def certificate_time_registry(self) -> dict[str, Any]:
        return await list_certificate_time_registry(bid_type=TECHNICAL_BID_TYPE)

    async def certificate_time_suggestions(self) -> dict[str, Any]:
        return await suggest_certificate_time_scopes(bid_type=TECHNICAL_BID_TYPE)

    async def update_certificate_time_scopes(self, data: dict[str, Any]) -> dict[str, Any]:
        return await update_certificate_time_scopes(
            bid_type=TECHNICAL_BID_TYPE,
            scopes=data.get("scopes") or [],
        )

    async def run_certificate_time_incremental(
        self,
        data: dict[str, Any],
        *,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        return await run_certificate_time_incremental(
            bid_type=TECHNICAL_BID_TYPE,
            limit=int(data.get("limit") or 0),
            include_failed=bool(data.get("includeFailed", True)),
            on_progress=on_progress,
        )

    async def recognize_certificate_time(self, file_id: str) -> dict[str, Any]:
        return await run_certificate_time_batch(
            bid_type=TECHNICAL_BID_TYPE,
            file_ids=[file_id],
            limit=1,
        )

    async def update_certificate_time(self, file_id: str, data: dict[str, Any]) -> dict[str, Any]:
        return await update_certificate_time_record(
            bid_type=TECHNICAL_BID_TYPE,
            file_id=file_id,
            issue_date=data.get("issueDate"),
            expiry_date=data.get("expiryDate"),
        )

    async def delete_certificate_time(self, file_id: str) -> dict[str, Any]:
        return await delete_certificate_time_record(
            bid_type=TECHNICAL_BID_TYPE,
            file_id=file_id,
        )

    async def delete_certificate_times(self, data: dict[str, Any]) -> dict[str, Any]:
        return await delete_certificate_time_records(
            bid_type=TECHNICAL_BID_TYPE,
            file_ids=data.get("fileIds") or [],
        )

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
        on_progress: Any = None,
    ) -> dict[str, Any]:
        payload = await material_store.import_generated_wiki_blueprint(
            root_title=root_title,
            root_markdown_content=root_markdown_content,
            nodes=nodes,
            mode=mode,
            bid_type=TECHNICAL_BID_TYPE,
            on_progress=on_progress,
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
