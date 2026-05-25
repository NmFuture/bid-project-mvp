from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from app.services.bid_type import BUSINESS_BID_TYPE, TECHNICAL_BID_TYPE, require_bid_type
from app.services.business_parse_assets import BusinessParseAssetError, sync_approved_business_parse_assets
from app.services.identity import build_project_material_scope
from app.services.template_store import template_fallback_payload
from app.services.workspace_project_access import (
    create_workspace_project,
    delete_workspace_project,
    get_workspace_project_detail,
    get_workspace_project_runtime_state,
    list_workspace_projects,
    update_workspace_project,
    update_workspace_project_stage,
    update_workspace_template_fallback,
    workspace_parse_progress,
    workspace_project_stages,
    workspace_template_fallback_context,
)


class BidProjectService:
    def __init__(
        self,
        *,
        bid_type: str,
        not_found_message: str,
        wrong_type_message: str,
        delete_message: str,
        clear_turbine_model: bool = False,
        sync_business_parse_assets: bool = False,
    ) -> None:
        self.bid_type = bid_type
        self.not_found_message = not_found_message
        self.wrong_type_message = wrong_type_message
        self.delete_message = delete_message
        self.clear_turbine_model = clear_turbine_model
        self.sync_business_parse_assets = sync_business_parse_assets

    def ensure_project(self, project_id: str) -> dict[str, Any]:
        return get_workspace_project_runtime_state(
            project_id,
            bid_type=self.bid_type,
            not_found_error=lambda _project_id: HTTPException(status_code=404, detail=self.not_found_message),
            wrong_type_error=lambda _project_id: HTTPException(status_code=400, detail=self.wrong_type_message),
        )

    def payload(self, data: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(data or {})
        payload["bidType"] = self.bid_type
        if self.clear_turbine_model:
            payload["turbineModel"] = payload.get("turbineModel") if isinstance(payload.get("turbineModel"), dict) else {}
        return payload

    def list(self, *, status: str = "", date_range: str = "", page: int = 1, page_size: int = 12) -> dict[str, Any]:
        return list_workspace_projects(
            status=status,
            bid_type=self.bid_type,
            date_range=date_range,
            page=page,
            page_size=page_size,
        )

    def create(self, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return create_workspace_project(self.payload(data))

    def get(self, project_id: str) -> dict[str, Any]:
        self.ensure_project(project_id)
        return get_workspace_project_detail(
            project_id,
            not_found_error=lambda _project_id: HTTPException(status_code=404, detail=self.not_found_message),
        )

    async def update(self, project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure_project(project_id)
        payload = self.payload(data)
        project = update_workspace_project(
            project_id,
            payload,
            not_found_error=lambda _project_id: HTTPException(status_code=404, detail=self.not_found_message),
        )
        decision = str((data or {}).get("reviewDecision") or "").strip().lower()
        if self.sync_business_parse_assets and decision == "participate":
            try:
                sync_result = await sync_approved_business_parse_assets(project_id)
            except BusinessParseAssetError as exc:
                project["businessParseAssetSync"] = {
                    "status": "failed",
                    "message": exc.detail,
                    "statusCode": exc.status_code,
                }
            else:
                project["businessParseAssetSync"] = {
                    key: value
                    for key, value in sync_result.items()
                    if key != "parseResult"
                }
        return project

    async def delete(self, project_id: str) -> dict[str, str]:
        self.ensure_project(project_id)
        await run_in_threadpool(
            delete_workspace_project,
            project_id,
            not_found_error=lambda _project_id: HTTPException(status_code=404, detail=self.not_found_message),
        )
        return {"message": self.delete_message}

    async def template_fallback(self, project_id: str) -> dict[str, Any]:
        self.ensure_project(project_id)
        context = workspace_template_fallback_context(
            project_id,
            not_found_error=lambda _project_id: HTTPException(status_code=404, detail=self.not_found_message),
        )
        return await template_fallback_payload(
            project_id=project_id,
            bid_type=self.bid_type,
            enabled=bool(context["enabled"]),
            source_id=str(context["sourceId"]),
            has_project_template=bool(context["hasProjectTemplate"]),
        )

    async def update_template_fallback(self, project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure_project(project_id)
        update_workspace_template_fallback(
            project_id,
            data or {},
            not_found_error=lambda _project_id: HTTPException(status_code=404, detail=self.not_found_message),
        )
        return await self.template_fallback(project_id)

    def parse_status(self, project_id: str) -> dict[str, Any]:
        self.ensure_project(project_id)
        return workspace_parse_progress(
            project_id,
            not_found_error=lambda _project_id: HTTPException(status_code=404, detail=self.not_found_message),
        )

    def stages(self, project_id: str) -> list[dict[str, Any]]:
        self.ensure_project(project_id)
        return workspace_project_stages(
            project_id,
            not_found_error=lambda _project_id: HTTPException(status_code=404, detail=self.not_found_message),
        )

    def update_stage(self, project_id: str, stage: int, data: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure_project(project_id)
        return update_workspace_project_stage(
            project_id,
            stage,
            data or {},
            not_found_error=lambda _project_id: HTTPException(status_code=404, detail=self.not_found_message),
        )

    def materials_path(self, project_id: str) -> dict[str, Any]:
        project = self.get(project_id)
        scope = build_project_material_scope(project)
        identity = scope["identity"]
        bid_type = require_bid_type(
            scope.get("bidType") or identity.get("bidType") or project.get("bidType"),
            error_message="项目素材路径必须显式绑定技术标或商务标。",
        )
        material_project_code = str(identity.get("projectCode") or project.get("projectCode") or project["id"])
        material_project_id = str(identity.get("projectId") or project["id"])
        return {
            "projectId": project["id"],
            "bidProjectId": project["id"],
            "bidProjectCode": project.get("projectCode") or project["id"],
            "materialProjectId": material_project_id,
            "materialProjectCode": material_project_code,
            "projectCode": material_project_code,
            "identity": identity,
            "turbineModel": project.get("turbineModel") or {},
            "turbineModelLabel": project.get("turbineModelLabel") or "",
            "path": f"{bid_type}/项目素材/{material_project_id}",
            "bidType": bid_type,
            "readableScopes": scope["readableScopes"],
            "paths": scope["paths"],
            "summary": scope["summary"],
        }


business_project_service = BidProjectService(
    bid_type=BUSINESS_BID_TYPE,
    not_found_message="商务标项目不存在。",
    wrong_type_message="该接口仅支持商务标项目。",
    delete_message="商务标项目已删除",
    clear_turbine_model=True,
    sync_business_parse_assets=True,
)

technical_project_service = BidProjectService(
    bid_type=TECHNICAL_BID_TYPE,
    not_found_message="技术标项目不存在。",
    wrong_type_message="该接口仅支持技术标项目。",
    delete_message="技术标项目已删除",
)
