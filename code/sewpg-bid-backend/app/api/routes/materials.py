from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import StreamingResponse

from app.api.utils import onlyoffice_backend_base_url
from app.services.business_material_splitter import (
    confirm_business_material_split,
    preview_business_material_split,
)
from app.services.material_store import material_store
from app.services.minio_client import minio_client
from app.services.wiki_generation import generate_platform_wiki

router = APIRouter()


@router.get("/api/materials/raw/permissions")
async def raw_permissions(role: str = Query(default="member")) -> dict[str, Any]:
    return await material_store.raw_permissions(role=role)


@router.get("/api/materials/raw/tree")
async def raw_tree() -> dict[str, Any]:
    return await material_store.raw_tree()


@router.get("/api/materials/identity-options")
async def identity_options(bidType: str = "") -> dict[str, Any]:
    return await material_store.identity_options(bid_type=bidType)


@router.get("/api/materials/turbine-model-options")
async def turbine_model_options(bidType: str = "技术标") -> dict[str, Any]:
    return await material_store.turbine_model_options(bid_type=bidType)


@router.get("/api/materials/raw/files")
async def raw_files(
    folderPath: str = "",
    projectId: str = "",
    customerName: str = "",
    bidType: str = "",
    materialTier: str = "",
    cleanStatus: str = "",
    keyword: str = "",
    turbineModel: str = "",
    recursive: bool = True,
    page: int = 1,
    pageSize: int = 20,
) -> dict[str, Any]:
    return await material_store.raw_files(
        folder_path=folderPath,
        project_id=projectId,
        customer_name=customerName,
        bid_type=bidType,
        material_tier=materialTier,
        clean_status=cleanStatus,
        keyword=keyword,
        turbine_model=turbineModel,
        recursive=recursive,
        page=page,
        page_size=pageSize,
    )


@router.post("/api/materials/raw/folders/bootstrap")
async def raw_bootstrap_folders(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await material_store.raw_bootstrap_folders(
        project_id=str(data.get("projectId") or ""),
        bid_type=str(data.get("bidType") or "技术标"),
    )


@router.post("/api/materials/raw/folders")
async def raw_create_folder(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await material_store.raw_create_folder(
        parent_path=str(data.get("parentPath") or ""),
        folder_name=str(data.get("folderName") or data.get("name") or ""),
    )


@router.delete("/api/materials/raw/folders")
async def raw_delete_folder(path: str = Query(default="")) -> dict[str, Any]:
    return await material_store.raw_delete_folder(path)


@router.post("/api/materials/raw/upload")
async def raw_upload(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    data: dict[str, Any]
    if "multipart/form-data" in content_type:
        form = await request.form()
        uploads = [upload for upload in form.getlist("files") if hasattr(upload, "filename") and hasattr(upload, "file")]
        relative_paths = [str(value or "") for value in form.getlist("relativePaths")]
        data = {
            "targetPath": str(form.get("targetPath") or ""),
            "projectId": str(form.get("projectId") or ""),
            "projectCode": str(form.get("projectCode") or ""),
            "projectName": str(form.get("projectName") or ""),
            "bidType": str(form.get("bidType") or "技术标"),
            "materialTier": str(form.get("materialTier") or ""),
            "businessMaterialKind": str(form.get("businessMaterialKind") or ""),
            "customerId": str(form.get("customerId") or ""),
            "customerName": str(form.get("customerName") or ""),
            "onConflict": str(form.get("onConflict") or ""),
            "files": [
                {
                    "name": str(getattr(upload, "filename", "") or ""),
                    "type": str(getattr(upload, "content_type", "") or ""),
                    "mimeType": str(getattr(upload, "content_type", "") or ""),
                    "relativePath": relative_paths[index] if index < len(relative_paths) else "",
                    "upload": upload,
                }
                for index, upload in enumerate(uploads)
            ],
        }
    else:
        try:
            data = await request.json()
        except Exception:
            data = {}
    return await material_store.raw_upload(
        target_path=str(data.get("targetPath") or ""),
        project_id=str(data.get("projectId") or ""),
        project_code=str(data.get("projectCode") or ""),
        project_name=str(data.get("projectName") or ""),
        bid_type=str(data.get("bidType") or "技术标"),
        material_tier=str(data.get("materialTier") or ""),
        business_material_kind=str(data.get("businessMaterialKind") or ""),
        customer_id=str(data.get("customerId") or ""),
        customer_name=str(data.get("customerName") or ""),
        on_conflict=str(data.get("onConflict") or ""),
        files=list(data.get("files") or []),
    )


@router.patch("/api/materials/raw/{file_id}")
async def raw_update_file(file_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await material_store.raw_update_file(
        file_id=file_id,
        name=str(data.get("name") or ""),
        business_material_kind=str(data.get("businessMaterialKind") or ""),
    )


@router.post("/api/materials/raw/move")
async def raw_move_file(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await material_store.raw_move_file(
        file_id=str(data.get("fileId") or ""),
        target_path=str(data.get("targetPath") or ""),
        on_conflict=str(data.get("onConflict") or ""),
    )


@router.post("/api/materials/raw/folders/move")
async def raw_move_folder(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await material_store.raw_move_folder(
        source_path=str(data.get("sourcePath") or ""),
        target_parent_path=str(data.get("targetParentPath") or data.get("targetPath") or ""),
    )


@router.delete("/api/materials/raw/{file_id}")
async def raw_delete_file(file_id: str) -> dict[str, Any]:
    return await material_store.raw_delete_file(file_id)


@router.get("/api/materials/raw/{file_id}/download")
async def raw_download_file(file_id: str) -> dict[str, Any]:
    return await material_store.raw_download_file(file_id)


@router.post("/api/materials/raw/{file_id}/business-split/preview")
async def raw_preview_business_split(file_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await preview_business_material_split(
        file_id,
        target_path=str(data.get("targetPath") or ""),
        ai_mode=str(data.get("aiMode") or "auto"),
    )


@router.post("/api/materials/raw/{file_id}/business-split/confirm")
async def raw_confirm_business_split(file_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await confirm_business_material_split(
        file_id,
        fragments=list(data.get("fragments") or []),
        default_target_path=str(data.get("targetPath") or ""),
        on_conflict=str(data.get("onConflict") or ""),
    )


@router.get("/api/materials/raw/{file_id}/content")
async def raw_download_content(file_id: str) -> StreamingResponse:
    payload = await material_store.raw_download_content(file_id)
    response = minio_client.get_object_response(payload["bucket"], payload["key"])

    def iterate_chunks():
        try:
            for chunk in response.stream(64 * 1024):
                yield chunk
        finally:
            response.close()
            response.release_conn()

    encoded_name = quote(str(payload["fileName"] or "download.bin"))
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
    }
    return StreamingResponse(
        iterate_chunks(),
        media_type=str(payload["mimeType"] or "application/octet-stream"),
        headers=headers,
    )


@router.post("/api/materials/raw/{file_id}/clean")
async def raw_retry_clean_file(file_id: str) -> dict[str, Any]:
    return await material_store.raw_retry_clean_file(file_id)


@router.get("/api/materials/raw/{file_id}/cleaned/download")
async def raw_download_cleaned_file(file_id: str) -> dict[str, Any]:
    return await material_store.raw_download_cleaned_file(file_id)


@router.get("/api/materials/raw/{file_id}/cleaned/preview")
async def raw_cleaned_preview(file_id: str, request: Request) -> dict[str, Any]:
    return await material_store.raw_cleaned_preview(
        file_id,
        browser_base_url=str(request.base_url).rstrip("/"),
        onlyoffice_base_url=onlyoffice_backend_base_url(request),
    )


def _cleaned_content_response(payload: dict[str, Any]) -> StreamingResponse:
    response = minio_client.get_object_response(payload["bucket"], payload["key"])

    def iterate_chunks():
        try:
            for chunk in response.stream(64 * 1024):
                yield chunk
        finally:
            response.close()
            response.release_conn()

    encoded_name = quote(str(payload["fileName"] or "cleaned.docx"))
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
    }
    return StreamingResponse(
        iterate_chunks(),
        media_type=str(payload["mimeType"] or "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        headers=headers,
    )


@router.get("/api/materials/raw/{file_id}/cleaned/content")
async def raw_download_cleaned_content(file_id: str) -> StreamingResponse:
    payload = await material_store.raw_download_cleaned_content(file_id)
    return _cleaned_content_response(payload)


@router.get("/api/materials/raw/{file_id}/cleaned/content/{filename:path}")
async def raw_download_cleaned_content_by_name(file_id: str, filename: str) -> StreamingResponse:
    payload = await material_store.raw_download_cleaned_content(file_id)
    return _cleaned_content_response(payload)


@router.get("/api/materials/structured")
async def structured_list(table: str = "all") -> dict[str, Any]:
    return await material_store.structured_list(table=table)


@router.get("/api/materials/structured/template")
async def structured_template(table: str = "") -> dict[str, Any]:
    return await material_store.structured_template(table=table)


@router.post("/api/materials/structured/import/preview")
async def structured_import_preview(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await material_store.structured_import_preview(
        table=str(data.get("table") or ""),
        payload=data,
    )


@router.post("/api/materials/structured/import/confirm")
async def structured_import_confirm(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await material_store.structured_confirm_import(
        table=str(data.get("table") or ""),
        payload=data,
    )


@router.post("/api/materials/structured")
async def structured_create(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await material_store.structured_create(data)


@router.put("/api/materials/structured/{item_id}")
async def structured_update(item_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await material_store.structured_update(item_id, data)


@router.delete("/api/materials/structured/{item_id}")
async def structured_delete(item_id: str) -> dict[str, Any]:
    return await material_store.structured_delete(item_id)


@router.post("/api/materials/structured/import")
async def structured_import_excel() -> dict[str, Any]:
    return await material_store.structured_import_excel()


@router.get("/api/materials/wiki")
async def wiki_list(nodeId: str = "", bidType: str = "") -> dict[str, Any]:
    return await material_store.wiki_list(nodeId, bidType)


@router.post("/api/materials/wiki/bootstrap")
async def wiki_bootstrap(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await generate_platform_wiki(
        reference_path=str(data.get("referencePath") or ""),
        mode=str(data.get("mode") or "create"),
        bid_type=str(data.get("bidType") or "技术标"),
        fallback_to_deterministic=bool(data.get("fallbackToDeterministic")),
    )


@router.post("/api/materials/wiki")
async def wiki_create(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await material_store.wiki_create(
        parent_id=str(data.get("parentId") or ""),
        title=str(data.get("title") or "新建节点"),
        is_folder=bool(data.get("isFolder")),
        bid_type=str(data.get("bidType") or ""),
    )


@router.put("/api/materials/wiki/{node_id}")
async def wiki_update(node_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await material_store.wiki_update(node_id, data)


@router.delete("/api/materials/wiki/{node_id}")
async def wiki_delete(node_id: str, bidType: str = Query(default="")) -> dict[str, Any]:
    return await material_store.wiki_delete(node_id, bidType)


@router.post("/api/materials/wiki/{node_id}/move")
async def wiki_move(node_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await material_store.wiki_move(
        node_id=node_id,
        target_id=str(data.get("targetId") or ""),
        mode=str(data.get("mode") or "inside"),
        bid_type=str(data.get("bidType") or ""),
    )


@router.post("/api/materials/wiki/{node_id}/attachments")
async def wiki_upload_attachment(node_id: str, request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        upload = form.get("file")
        return await material_store.wiki_upload_attachment(
            node_id=node_id,
            file_name=str(getattr(upload, "filename", "") or form.get("fileName") or ""),
            file_size=form.get("fileSize"),
            upload=upload,
            mime_type=str(getattr(upload, "content_type", "") or ""),
            bid_type=str(form.get("bidType") or ""),
        )

    data = await request.json()
    raw_bytes = data.get("data")
    decoded = None
    if raw_bytes is not None:
        raw_text = str(raw_bytes)
        if raw_text.startswith("data:"):
            raw_text = raw_text.split(",", 1)[-1]
        decoded = base64.b64decode(raw_text)
    return await material_store.wiki_upload_attachment(
        node_id=node_id,
        file_name=str(data.get("fileName") or ""),
        file_size=data.get("fileSize"),
        data=decoded,
        mime_type=str(data.get("mimeType") or ""),
        bid_type=str(data.get("bidType") or ""),
    )


@router.post("/api/materials/wiki/{node_id}/refresh-summary")
async def wiki_refresh_summary(node_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await material_store.wiki_refresh_summary(node_id, str(data.get("bidType") or ""))


@router.get("/api/materials/wiki/attachments/{attachment_id}/content")
async def wiki_download_attachment_content(attachment_id: str) -> StreamingResponse:
    payload = await material_store.wiki_download_attachment_content(attachment_id)
    response = minio_client.get_object_response(payload["bucket"], payload["key"])

    def iterate_chunks():
        try:
            for chunk in response.stream(64 * 1024):
                yield chunk
        finally:
            response.close()
            response.release_conn()

    encoded_name = quote(str(payload["fileName"] or "attachment.bin"))
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
    }
    return StreamingResponse(
        iterate_chunks(),
        media_type=str(payload["mimeType"] or "application/octet-stream"),
        headers=headers,
    )


@router.delete("/api/materials/wiki/attachments/{attachment_id}")
async def wiki_delete_attachment(attachment_id: str, bidType: str = Query(default="")) -> dict[str, Any]:
    return await material_store.wiki_delete_attachment(attachment_id, bidType)
