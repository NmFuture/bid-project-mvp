from __future__ import annotations

from typing import Any

import base64

from fastapi import APIRouter, Body, Depends, Request

from app.services.auth_service import auth_service, current_user
from app.services.system_settings import system_settings_service

router = APIRouter()


@router.get("/api/settings/users")
async def settings_users(_: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return await auth_service.list_users()


@router.post("/api/settings/users")
async def settings_create_user(
    data: dict[str, Any] = Body(default_factory=dict),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return await auth_service.create_user(data, operator=user)


@router.put("/api/settings/users/{user_id}")
async def settings_update_user(
    user_id: str,
    data: dict[str, Any] = Body(default_factory=dict),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return await auth_service.update_user(user_id, data, operator=user)


@router.get("/api/settings/llm-gateway")
async def settings_gateway_get(_: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    payload = await system_settings_service.get_model_config("llm")
    return {
        **payload,
        "endpoint": payload.get("baseUrl") or "",
        "modelId": payload.get("modelId") or payload.get("model") or "",
    }


@router.put("/api/settings/llm-gateway")
async def settings_gateway_update(
    data: dict[str, Any] = Body(default_factory=dict),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    payload = await system_settings_service.update_model_config("llm", data, user=user)
    payload["config"]["endpoint"] = payload["config"].get("baseUrl") or ""
    payload["config"]["modelId"] = payload["config"].get("modelId") or payload["config"].get("model") or ""
    return payload


@router.post("/api/settings/llm-gateway/test")
async def settings_gateway_test(
    data: dict[str, Any] = Body(default_factory=dict),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return await system_settings_service.test_model_config("llm", data, user=user)


@router.get("/api/settings/ocr")
async def settings_ocr_get(_: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return await system_settings_service.get_model_config("ocr")


@router.put("/api/settings/ocr")
async def settings_ocr_update(
    data: dict[str, Any] = Body(default_factory=dict),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return await system_settings_service.update_model_config("ocr", data, user=user)


@router.post("/api/settings/ocr/test")
async def settings_ocr_test(
    data: dict[str, Any] = Body(default_factory=dict),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return await system_settings_service.test_model_config("ocr", data, user=user)


def _decode_request_bytes(raw: Any) -> bytes | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw
    text = str(raw)
    if text.startswith("data:"):
        text = text.split(",", 1)[-1]
    return base64.b64decode(text)


@router.get("/api/settings/default-templates")
async def settings_default_templates_list(_: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return await system_settings_service.default_templates_list()


@router.post("/api/settings/default-templates")
async def settings_default_templates_upload(
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        upload = form.get("file")
        return await system_settings_service.default_template_upload(
            template_type=str(form.get("templateType") or ""),
            file_name=str(getattr(upload, "filename", "") or form.get("fileName") or ""),
            version=str(form.get("version") or ""),
            upload=upload,
            mime_type=str(getattr(upload, "content_type", "") or ""),
            user=user,
        )
    data = await request.json()
    return await system_settings_service.default_template_upload(
        template_type=str(data.get("templateType") or ""),
        file_name=str(data.get("fileName") or ""),
        version=str(data.get("version") or ""),
        data=_decode_request_bytes(data.get("data")),
        mime_type=str(data.get("mimeType") or ""),
        user=user,
    )


@router.post("/api/settings/default-templates/{template_id}/activate")
async def settings_default_templates_activate(
    template_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return await system_settings_service.default_template_activate(template_id, user=user)


@router.delete("/api/settings/default-templates/{template_id}")
async def settings_default_templates_delete(
    template_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return await system_settings_service.default_template_delete(template_id, user=user)


@router.get("/api/settings/health")
async def settings_health(_: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    return await system_settings_service.health()
