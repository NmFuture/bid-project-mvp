from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query

from app.services.peripheral import peripheral_store

router = APIRouter()


@router.get("/api/materials/raw/permissions")
async def raw_permissions(role: str = Query(default="member")) -> dict[str, Any]:
    return peripheral_store.raw_permissions(role=role)


@router.get("/api/materials/raw/tree")
async def raw_tree() -> dict[str, Any]:
    return peripheral_store.raw_tree()


@router.get("/api/materials/raw/files")
async def raw_files(
    folderPath: str = "",
    projectId: str = "",
    customerName: str = "",
    bidType: str = "",
    keyword: str = "",
    page: int = 1,
    pageSize: int = 20,
) -> dict[str, Any]:
    return peripheral_store.raw_files(
        folder_path=folderPath,
        project_id=projectId,
        customer_name=customerName,
        bid_type=bidType,
        keyword=keyword,
        page=page,
        page_size=pageSize,
    )


@router.post("/api/materials/raw/folders/bootstrap")
async def raw_bootstrap_folders(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return peripheral_store.raw_bootstrap_folders(
        project_id=str(data.get("projectId") or ""),
        bid_type=str(data.get("bidType") or "技术标"),
    )


@router.post("/api/materials/raw/folders")
async def raw_create_folder(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return peripheral_store.raw_create_folder(
        parent_path=str(data.get("parentPath") or ""),
        folder_name=str(data.get("folderName") or data.get("name") or ""),
    )


@router.delete("/api/materials/raw/folders")
async def raw_delete_folder(path: str = Query(default="")) -> dict[str, Any]:
    return peripheral_store.raw_delete_folder(path)


@router.post("/api/materials/raw/upload")
async def raw_upload(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return peripheral_store.raw_upload(
        target_path=str(data.get("targetPath") or ""),
        project_id=str(data.get("projectId") or ""),
        bid_type=str(data.get("bidType") or "技术标"),
        on_conflict=str(data.get("onConflict") or ""),
        files=list(data.get("files") or []),
    )


@router.patch("/api/materials/raw/{file_id}")
async def raw_update_file(file_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return peripheral_store.raw_update_file(file_id=file_id, name=str(data.get("name") or ""))


@router.post("/api/materials/raw/move")
async def raw_move_file(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return peripheral_store.raw_move_file(
        file_id=str(data.get("fileId") or ""),
        target_path=str(data.get("targetPath") or ""),
        on_conflict=str(data.get("onConflict") or ""),
    )


@router.delete("/api/materials/raw/{file_id}")
async def raw_delete_file(file_id: str) -> dict[str, Any]:
    return peripheral_store.raw_delete_file(file_id)


@router.get("/api/materials/raw/{file_id}/download")
async def raw_download_file(file_id: str) -> dict[str, Any]:
    return peripheral_store.raw_download_file(file_id)


@router.get("/api/materials/structured")
async def structured_list(table: str = "all") -> dict[str, Any]:
    return peripheral_store.structured_list(table=table)


@router.get("/api/materials/structured/template")
async def structured_template(table: str = "") -> dict[str, Any]:
    return peripheral_store.structured_template(table=table)


@router.post("/api/materials/structured/import/preview")
async def structured_import_preview(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return peripheral_store.structured_preview_import(
        table=str(data.get("table") or ""),
        payload=data,
    )


@router.post("/api/materials/structured/import/confirm")
async def structured_import_confirm(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return peripheral_store.structured_confirm_import(
        table=str(data.get("table") or ""),
        payload=data,
    )


@router.post("/api/materials/structured")
async def structured_create(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return peripheral_store.structured_create(data)


@router.put("/api/materials/structured/{item_id}")
async def structured_update(item_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return peripheral_store.structured_update(item_id, data)


@router.delete("/api/materials/structured/{item_id}")
async def structured_delete(item_id: str) -> dict[str, Any]:
    return peripheral_store.structured_delete(item_id)


@router.post("/api/materials/structured/import")
async def structured_import_excel() -> dict[str, Any]:
    return peripheral_store.structured_import_excel()


@router.get("/api/materials/wiki")
async def wiki_list(nodeId: str = "") -> dict[str, Any]:
    return peripheral_store.wiki_list(nodeId)


@router.post("/api/materials/wiki")
async def wiki_create(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return peripheral_store.wiki_create(
        parent_id=str(data.get("parentId") or ""),
        title=str(data.get("title") or "新建节点"),
        is_folder=bool(data.get("isFolder")),
    )


@router.put("/api/materials/wiki/{node_id}")
async def wiki_update(node_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return peripheral_store.wiki_update(node_id, data)


@router.post("/api/materials/wiki/{node_id}/move")
async def wiki_move(node_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return peripheral_store.wiki_move(
        node_id=node_id,
        target_id=str(data.get("targetId") or ""),
        mode=str(data.get("mode") or "inside"),
    )


@router.post("/api/materials/wiki/{node_id}/attachments")
async def wiki_upload_attachment(node_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return peripheral_store.wiki_upload_attachment(
        node_id=node_id,
        file_name=str(data.get("fileName") or ""),
        file_size=data.get("fileSize"),
    )


@router.post("/api/materials/wiki/{node_id}/refresh-summary")
async def wiki_refresh_summary(node_id: str) -> dict[str, Any]:
    return peripheral_store.wiki_refresh_summary(node_id)
