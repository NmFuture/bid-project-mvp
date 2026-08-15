from __future__ import annotations

import copy
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from app.services.bid_type import BUSINESS_BID_TYPE, TECHNICAL_BID_TYPE, require_bid_type
from app.services.bid_project_state import update_project_state
from app.services.business_parse_assets import BusinessParseAssetError, sync_approved_business_parse_assets
from app.services.identity import build_project_material_scope
from app.services.material_folder_scope import project_material_root_path
from app.services.peripheral import PeripheralError
from app.services.template_store import template_fallback_payload
from app.services.technical_parse_asset_sync_job import (
    recover_stale_technical_parse_asset_sync,
    schedule_technical_parse_asset_sync,
)
from app.services.technical_project_material_copy_job import schedule_technical_material_copy
from app.services.technical_project_material_folder import (
    prepare_technical_project_material_folder,
    resolve_technical_project_folder_path,
)
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
        sync_technical_parse_assets: bool = False,
        bootstrap_material_folder: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
    ) -> None:
        self.bid_type = bid_type
        self.not_found_message = not_found_message
        self.wrong_type_message = wrong_type_message
        self.delete_message = delete_message
        self.clear_turbine_model = clear_turbine_model
        self.sync_business_parse_assets = sync_business_parse_assets
        self.sync_technical_parse_assets = sync_technical_parse_assets
        self.bootstrap_material_folder = bootstrap_material_folder

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
            payload["turbineModel"] = {}
            payload["selectedTurbineModel"] = {}
            payload["machineModel"] = ""
            payload["turbineModels"] = []
        return payload

    def list(
        self,
        *,
        status: str = "",
        review_decision: str = "",
        date_range: str = "",
        page: int = 1,
        page_size: int = 12,
    ) -> dict[str, Any]:
        return list_workspace_projects(
            status=status,
            bid_type=self.bid_type,
            review_decision=review_decision,
            date_range=date_range,
            page=page,
            page_size=page_size,
        )

    def create(self, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return create_workspace_project(self.payload(data))

    def get(self, project_id: str) -> dict[str, Any]:
        self.ensure_project(project_id)
        if self.sync_technical_parse_assets:
            recover_stale_technical_parse_asset_sync(project_id)
        return get_workspace_project_detail(
            project_id,
            not_found_error=lambda _project_id: HTTPException(status_code=404, detail=self.not_found_message),
        )

    async def update(self, project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        current_project = self.ensure_project(project_id)
        payload = self.payload(data)
        decision = str((data or {}).get("reviewDecision") or "").strip().lower()
        candidate_payload = dict(payload)
        candidate_payload.pop("reviewDecision", None)
        candidate_project = update_project_state(
            copy.deepcopy(current_project),
            project_id,
            candidate_payload,
        )
        bootstrap_status: dict[str, Any] | None = None
        should_bootstrap = self.bootstrap_material_folder is not None and (
            decision == "participate"
            or (
                str(current_project.get("reviewDecision") or "").strip().lower() == "participate"
                and any(
                    field in (data or {})
                    for field in ("name", "materialProjectId", "materialProjectMode")
                )
            )
        )
        # 素材来源只在首次确认参与时生效一次：已记过来源就不再复制，避免重复堆文件。
        copy_source_project_id = ""
        if self.bid_type == TECHNICAL_BID_TYPE and not str(current_project.get("materialSourceProjectId") or "").strip():
            copy_source_project_id = str((data or {}).get("materialSourceProjectId") or "").strip()
        if should_bootstrap:
            if self.bid_type == TECHNICAL_BID_TYPE:
                project_name = str(candidate_project.get("name") or "").strip()
                if not project_name:
                    raise HTTPException(status_code=400, detail="请先完善项目名称。")
                existing_projects = list_workspace_projects(
                    bid_type=TECHNICAL_BID_TYPE,
                    page=1,
                    page_size=1_000_000,
                ).get("items") or []
                if any(
                    str(item.get("id") or "") != project_id
                    and str(item.get("name") or "").strip() == project_name
                    for item in existing_projects
                ):
                    raise HTTPException(status_code=409, detail="已存在相同项目，请修改项目名称。")
                parse_result = (
                    current_project.get("parse_result")
                    if isinstance(current_project.get("parse_result"), dict)
                    else {}
                )
                structured = (
                    parse_result.get("structured")
                    if isinstance(parse_result.get("structured"), dict)
                    else {}
                )
                sync_state = (
                    structured.get("technicalAppendixMaterialSync")
                    if isinstance(structured.get("technicalAppendixMaterialSync"), dict)
                    else {}
                )
                appendix_material_ids = [
                    str(item.get("materialId") or "")
                    for item in sync_state.get("items") or []
                    if isinstance(item, dict) and str(item.get("materialId") or "")
                ]
                try:
                    bootstrap_status = await prepare_technical_project_material_folder(
                        candidate_project,
                        appendix_material_ids=appendix_material_ids,
                    )
                except PeripheralError as exc:
                    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
            else:
                material_scope = build_project_material_scope(candidate_project)
                identity = material_scope["identity"]
                material_project_id = str(identity.get("projectId") or project_id)
                project_scope = next(
                    (item for item in material_scope["readableScopes"] if item.get("key") == "project"),
                    {},
                )
                bootstrap_result = await self.bootstrap_material_folder(material_project_id)
                bootstrap_payload = (
                    bootstrap_result.get("payload")
                    if isinstance(bootstrap_result, dict) and isinstance(bootstrap_result.get("payload"), dict)
                    else {}
                )
                bootstrap_status = {
                    "status": "ok",
                    "projectId": material_project_id,
                    "path": str(bootstrap_payload.get("path") or project_scope.get("path") or ""),
                }
        business_sync_status: dict[str, Any] | None = None
        if self.sync_business_parse_assets and decision == "participate":
            try:
                sync_result = await sync_approved_business_parse_assets(project_id)
            except BusinessParseAssetError as exc:
                raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
            business_sync_status = {
                key: value
                for key, value in sync_result.items()
                if key != "parseResult"
            }
        project = update_workspace_project(
            project_id,
            payload,
            not_found_error=lambda _project_id: HTTPException(status_code=404, detail=self.not_found_message),
        )
        if bootstrap_status is not None:
            project["materialFolderBootstrap"] = bootstrap_status
            target_path = str(bootstrap_status.get("path") or "")
            if copy_source_project_id and target_path:
                source_path = await resolve_technical_project_folder_path(copy_source_project_id)
                if not source_path:
                    raise HTTPException(status_code=404, detail="来源项目的素材目录不存在，请重新选择项目来源。")
                project["materialCopyState"] = schedule_technical_material_copy(
                    project_id,
                    source_path=source_path,
                    target_path=target_path,
                    source_project_id=copy_source_project_id,
                )
        if business_sync_status is not None:
            project["businessParseAssetSync"] = business_sync_status
        if self.sync_technical_parse_assets and decision == "participate":
            project["technicalParseAssetSyncState"] = schedule_technical_parse_asset_sync(project_id)
        return project

    async def delete(self, project_id: str) -> dict[str, Any]:
        self.ensure_project(project_id)
        workspace_cleanup = await run_in_threadpool(
            delete_workspace_project,
            project_id,
            not_found_error=lambda _project_id: HTTPException(status_code=404, detail=self.not_found_message),
        )
        payload: dict[str, Any] = {"message": self.delete_message}
        failures = list((workspace_cleanup or {}).get("failures") or [])
        if failures:
            # 磁盘没清干净不能报成功了事：残留的工作区会被后续项目继承，
            # 这里把失败项摆到响应里，让调用方当场看见而不是等磁盘涨满才发现。
            payload["workspaceCleanupFailed"] = failures
            payload["message"] = f"{self.delete_message}（磁盘工作区有 {len(failures)} 项未清理，详见 workspaceCleanupFailed）"
        return payload

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
        project_scope = next(
            (item for item in scope["readableScopes"] if item.get("key") == "project"),
            {},
        )
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
            "path": str(
                project_scope.get("path")
                or project_material_root_path(bid_type, material_project_id)
            ),
            "bidType": bid_type,
            "readableScopes": scope["readableScopes"],
            "paths": scope["paths"],
            "summary": scope["summary"],
        }


async def _bootstrap_technical_material_folder(material_project_id: str) -> dict[str, Any]:
    # 延迟导入：technical_material_store 依赖链较重，避免模块加载期循环引用。
    from app.services.technical_material_store import technical_material_store

    return await technical_material_store.raw_bootstrap_folders(material_project_id)


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
    sync_technical_parse_assets=True,
    bootstrap_material_folder=_bootstrap_technical_material_folder,
)
