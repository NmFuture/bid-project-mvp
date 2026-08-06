from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException, Request

from app.services.bid_document_state import apply_technical_document_format_to_project
from app.services.bid_document_flow import BidDocumentService
from app.services.bid_document_flow import _build_document_payload
from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.bid_project_service import technical_project_service
from app.services.onlyoffice_documents import (
    document_object_key,
    ensure_document,
    refresh_document_session,
    sync_document_to_minio,
)
from app.services.technical_document_format import TECH_FORMAT_PRESETS, apply_technical_document_format_preset
from app.services.url_utils import now_message
from app.services.workspace_project_access import persist_workspace_project_state, require_workspace_project_for_update

def _technical_project_for_update(project_id: str) -> dict[str, Any]:
    return require_workspace_project_for_update(
        project_id,
        bid_type=TECHNICAL_BID_TYPE,
        not_found_error=lambda _project_id: HTTPException(
            status_code=404,
            detail=technical_project_service.not_found_message,
        ),
        wrong_type_error=lambda _project_id: HTTPException(
            status_code=400,
            detail=technical_project_service.wrong_type_message,
        ),
    )


class TechnicalDocumentService(BidDocumentService):
    async def apply_format(self, project_id: str, request: Request, data: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure_project(project_id)
        preset = str((data or {}).get("preset") or "standard").strip() or "standard"
        if preset not in TECH_FORMAT_PRESETS:
            raise HTTPException(status_code=400, detail="未知技术标格式预设。")
        style_overrides = (data or {}).get("styleOverrides") if isinstance((data or {}).get("styleOverrides"), dict) else None
        try:
            result = await asyncio.to_thread(
                apply_technical_document_format_preset,
                project_id,
                preset,
                style_overrides,
            )
            project_state = _technical_project_for_update(project_id)
            state = apply_technical_document_format_to_project(project_state, result)
            persist_workspace_project_state(project_state)
            doc_path = ensure_document(project_id, state["fileName"], state["fallback"]["content"])
            refresh_document_session(doc_path)
            sync_document_to_minio(doc_path, document_object_key(project_id))
            return now_message(
                f"已应用{result.get('label') or '技术标格式'}。",
                {
                    "format": result,
                    "document": _build_document_payload(project_id, request, self.api_prefix, state),
                },
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"技术标格式切换失败：{exc}") from exc


technical_document_service = TechnicalDocumentService(technical_project_service, "/api/technical/projects")
