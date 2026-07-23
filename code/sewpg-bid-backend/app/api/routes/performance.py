from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.api.utils import minio_streaming_response, onlyoffice_backend_base_url
from app.services.performance_library_service import performance_library_service
from app.services.performance_package_service import performance_package_service

router = APIRouter()


@router.get("/api/materials/performance")
async def list_performance_records(
    keyword: str = "",
    customerName: str = "",
    bidType: str = "",
    tag: str = "",
    page: int = 1,
    pageSize: int = 20,
) -> dict[str, Any]:
    return await performance_library_service.list_records(
        keyword=keyword,
        customer_name=customerName,
        bid_type=bidType,
        tag=tag,
        page=page,
        page_size=pageSize,
    )


@router.get("/api/materials/performance/categories")
async def list_performance_categories(
    keyword: str = "",
    scene: str = "",
    powerRating: str = "",
    turbineModel: str = "",
    timeKeyword: str = "",
    contractYear: str = "",
    deliveryYear: str = "",
    operationYear: str = "",
    tag: str = "",
    status: str = "enabled",
    sortBy: str = "updatedAt",
    sortOrder: str = "desc",
    page: int = 1,
    pageSize: int = 20,
) -> dict[str, Any]:
    return await performance_package_service.list_categories(
        keyword=keyword,
        scene=scene,
        power_rating=powerRating,
        turbine_model=turbineModel,
        time_keyword=timeKeyword,
        contract_year=contractYear,
        delivery_year=deliveryYear,
        operation_year=operationYear,
        tag=tag,
        status=status,
        sort_by=sortBy,
        sort_order=sortOrder,
        page=page,
        page_size=pageSize,
    )


@router.get("/api/materials/performance/items")
async def list_performance_items(
    keyword: str = "",
    turbineModel: str = "",
    timeKeyword: str = "",
    contractYear: str = "",
    deliveryYear: str = "",
    operationYear: str = "",
    categoryId: str = "",
    status: str = "enabled",
    sortBy: str = "updatedAt",
    sortOrder: str = "desc",
    page: int = 1,
    pageSize: int = 20,
) -> dict[str, Any]:
    return await performance_package_service.list_items(
        keyword=keyword,
        turbine_model=turbineModel,
        time_keyword=timeKeyword,
        contract_year=contractYear,
        delivery_year=deliveryYear,
        operation_year=operationYear,
        category_id=categoryId,
        status=status,
        sort_by=sortBy,
        sort_order=sortOrder,
        page=page,
        page_size=pageSize,
    )


@router.post("/api/materials/performance/categories/preview")
async def preview_performance_summary(file: UploadFile = File(...)) -> dict[str, Any]:
    try:
        return await performance_package_service.preview_summary(file)
    finally:
        await file.close()


@router.post("/api/materials/performance/categories/import")
async def import_performance_summary(
    file: UploadFile = File(...),
    contractFiles: list[UploadFile] = File(default_factory=list),
    categoryName: str = Form(""),
    scene: str = Form(""),
    powerRating: str = Form(""),
    tags: str = Form(""),
    scope: str = Form("standard"),
    reviewStatus: str = Form("draft"),
) -> dict[str, Any]:
    try:
        return await performance_package_service.import_summary(
            file,
            contract_uploads=contractFiles,
            category_name=categoryName,
            scene=scene,
            power_rating=powerRating,
            tags=tags,
            scope=scope,
            review_status=reviewStatus,
        )
    finally:
        await file.close()
        for contract_file in contractFiles:
            await contract_file.close()


@router.get("/api/materials/performance/categories/{category_id}")
async def get_performance_category(category_id: str) -> dict[str, Any]:
    return await performance_package_service.get_category(category_id)


@router.delete("/api/materials/performance/categories/{category_id}")
async def delete_performance_category(category_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await performance_package_service.delete_category(category_id, confirm_name=str(data.get("confirmName") or ""))


@router.patch("/api/materials/performance/categories/{category_id}/status")
async def update_performance_category_status(category_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await performance_package_service.update_category_status(category_id, str(data.get("status") or ""))


@router.post("/api/materials/performance/categories/{category_id}/attachments")
async def upload_performance_category_attachment(
    category_id: str,
    file: UploadFile = File(...),
    attachmentType: str = Form("contract_bundle"),
) -> dict[str, Any]:
    try:
        return await performance_package_service.upload_attachment(
            category_id,
            file,
            attachment_type=attachmentType,
        )
    finally:
        await file.close()


@router.get("/api/materials/performance/categories/{category_id}/attachments/{attachment_id}")
async def download_performance_category_attachment(category_id: str, attachment_id: str) -> StreamingResponse:
    payload = await performance_package_service.download_attachment(category_id, attachment_id)
    return minio_streaming_response(payload)


@router.get("/api/materials/performance/categories/{category_id}/attachments/{attachment_id}/preview")
async def preview_performance_category_attachment(category_id: str, attachment_id: str, request: Request) -> dict[str, Any]:
    return await performance_package_service.preview_attachment(
        category_id,
        attachment_id,
        browser_base_url=str(request.base_url).rstrip("/"),
        onlyoffice_base_url=onlyoffice_backend_base_url(request),
    )


@router.patch("/api/materials/performance/categories/{category_id}/items/{item_id}")
async def update_performance_item(category_id: str, item_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await performance_package_service.update_item(category_id, item_id, data)


@router.get("/api/materials/performance/categories/{category_id}/items/{item_id}/attachments/{attachment_id}")
async def download_performance_item_attachment(category_id: str, item_id: str, attachment_id: str) -> StreamingResponse:
    payload = await performance_package_service.download_item_attachment(category_id, item_id, attachment_id)
    return minio_streaming_response(payload)


@router.get("/api/materials/performance/categories/{category_id}/items/{item_id}/attachments/{attachment_id}/preview")
async def preview_performance_item_attachment(category_id: str, item_id: str, attachment_id: str, request: Request) -> dict[str, Any]:
    return await performance_package_service.preview_item_attachment(
        category_id,
        item_id,
        attachment_id,
        browser_base_url=str(request.base_url).rstrip("/"),
        onlyoffice_base_url=onlyoffice_backend_base_url(request),
    )


@router.post("/api/materials/performance")
async def create_performance_record(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return await performance_library_service.create_record(data)


@router.put("/api/materials/performance/{record_id}")
async def update_performance_record(
    record_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    return await performance_library_service.update_record(record_id, data)


@router.delete("/api/materials/performance/{record_id}")
async def delete_performance_record(record_id: str) -> dict[str, Any]:
    return await performance_library_service.delete_record(record_id)


@router.post("/api/materials/performance/{record_id}/word")
async def upload_performance_word(record_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    try:
        return await performance_library_service.upload_word(record_id, file)
    finally:
        await file.close()


@router.get("/api/materials/performance/{record_id}/word")
async def download_performance_word(record_id: str) -> StreamingResponse:
    payload = await performance_library_service.download_word(record_id)
    return minio_streaming_response(payload)
