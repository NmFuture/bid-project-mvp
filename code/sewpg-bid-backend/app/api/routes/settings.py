from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from app.services.peripheral import peripheral_store

router = APIRouter()


@router.get("/api/settings/users")
async def settings_users() -> dict[str, Any]:
    return peripheral_store.settings_users()


@router.post("/api/settings/users")
async def settings_create_user(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return peripheral_store.settings_create_user(data)


@router.put("/api/settings/users/{user_id}")
async def settings_update_user(user_id: str, data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return peripheral_store.settings_update_user(user_id, data)


@router.get("/api/settings/llm-gateway")
async def settings_gateway_get() -> dict[str, Any]:
    return peripheral_store.settings_gateway_get()


@router.put("/api/settings/llm-gateway")
async def settings_gateway_update(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return peripheral_store.settings_gateway_update(data)


@router.post("/api/settings/llm-gateway/test")
async def settings_gateway_test(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return peripheral_store.settings_gateway_test(
        endpoint=str(data.get("endpoint") or ""),
        model=str(data.get("model") or ""),
    )


@router.get("/api/settings/dotx-templates")
async def settings_dotx_list() -> dict[str, Any]:
    return peripheral_store.settings_dotx_list()


@router.post("/api/settings/dotx-templates")
async def settings_dotx_upload(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return peripheral_store.settings_dotx_upload(
        file_name=str(data.get("fileName") or ""),
        file_size=data.get("fileSize"),
        version=str(data.get("version") or "2026.04"),
    )


@router.post("/api/settings/dotx-templates/{template_id}/activate")
async def settings_dotx_activate(template_id: str) -> dict[str, Any]:
    return peripheral_store.settings_dotx_activate(template_id)


@router.get("/api/settings/excel-templates")
async def settings_excel_list() -> dict[str, Any]:
    return peripheral_store.settings_excel_list()


@router.post("/api/settings/excel-templates")
async def settings_excel_upload(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return peripheral_store.settings_excel_upload(
        table_key=str(data.get("tableKey") or ""),
        file_name=str(data.get("fileName") or ""),
        version=str(data.get("version") or "2026.04"),
    )


@router.post("/api/settings/excel-templates/{template_id}/activate")
async def settings_excel_activate(template_id: str) -> dict[str, Any]:
    return peripheral_store.settings_excel_activate(template_id)


@router.get("/api/settings/backups")
async def settings_backups_list() -> dict[str, Any]:
    return peripheral_store.settings_backups_list()


@router.post("/api/settings/backups/create")
async def settings_backups_create(data: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return peripheral_store.settings_backups_create(str(data.get("note") or ""))


@router.post("/api/settings/backups/{backup_id}/restore")
async def settings_backups_restore(backup_id: str) -> dict[str, Any]:
    return peripheral_store.settings_backups_restore(backup_id)


@router.get("/api/settings/health")
async def settings_health() -> list[dict[str, Any]]:
    return peripheral_store.settings_health()
