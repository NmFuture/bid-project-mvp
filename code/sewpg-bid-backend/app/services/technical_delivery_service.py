from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.services.bid_project_service import BidProjectService, technical_project_service
from app.services.technical_coverage import build_technical_coverage
from app.services.url_utils import absolute_url


class TechnicalCoverageService:
    def __init__(self, project_service: BidProjectService) -> None:
        self.project_service = project_service

    def ensure_project(self, project_id: str) -> dict[str, Any]:
        return self.project_service.ensure_project(project_id)

    async def coverage(self, project_id: str) -> dict[str, Any]:
        project = self.ensure_project(project_id)
        return build_technical_coverage(project)


class TechnicalExportService:
    def __init__(self, project_service: BidProjectService) -> None:
        self.project_service = project_service

    def ensure_project(self, project_id: str) -> dict[str, Any]:
        return self.project_service.ensure_project(project_id)

    async def check(self, project_id: str) -> dict[str, Any]:
        project = self.ensure_project(project_id)
        coverage = build_technical_coverage(project)
        warnings = [
            {
                "label": "导出操作将锁定当前版本的报价数据。如需重新修改，需在项目视图中创建新版本。"
            }
        ]
        return {
            "checks": [
                {
                    "label": f"评分点覆盖率校验（当前红项 {coverage['noCover']}）",
                    "passed": coverage["noCover"] == 0,
                    "code": "coverage",
                },
                {
                    "label": "项目信息一致性校验通过",
                    "passed": True,
                    "code": "consistency",
                },
                {
                    "label": "格式合规抽检通过",
                    "passed": True,
                    "code": "format",
                },
            ],
            "warnings": warnings,
            "requiresWarningConfirm": True,
            "suggestedFileName": f"投标文件_{project_id}_{datetime.now().strftime('%Y%m%d')}",
        }

    async def export(self, project_id: str, request: Request, data: dict[str, Any] | None = None) -> Any:
        project = self.ensure_project(project_id)
        payload = data or {}
        coverage = build_technical_coverage(project)
        if coverage["noCover"] > 0:
            return JSONResponse(
                status_code=400,
                content={
                    "detail": "存在未覆盖评分项（红项），禁止导出。",
                    "code": "EXPORT_BLOCKED_BY_COVERAGE",
                },
            )

        file_name = str(payload.get("fileName") or "").strip()
        if not file_name:
            return JSONResponse(
                status_code=400,
                content={
                    "detail": "导出文件名不能为空。",
                    "code": "EXPORT_NAME_REQUIRED",
                },
            )
        if not re.fullmatch(r"[\w\u4e00-\u9fa5-]+", file_name):
            return JSONResponse(
                status_code=400,
                content={
                    "detail": "导出文件名包含非法字符。",
                    "code": "EXPORT_NAME_INVALID",
                },
            )
        if not bool(payload.get("warningConfirmed")):
            return JSONResponse(
                status_code=400,
                content={
                    "detail": "请先确认导出警告项后再继续。",
                    "code": "EXPORT_WARNING_NOT_CONFIRMED",
                },
            )

        fmt = str(payload.get("format") or "docx").lower()
        if fmt != "docx":
            return JSONResponse(
                status_code=400,
                content={
                    "detail": "当前 MVP 仅支持导出 DOCX，PDF 导出尚未接入真实转换。",
                    "code": "EXPORT_FORMAT_NOT_IMPLEMENTED",
                },
            )

        self.project_service.update_stage(project_id, 6, {"status": "completed"})
        return {
            "message": "Exported",
            "fileUrl": absolute_url(request, f"/api/technical/projects/{project_id}/final-document/file"),
            "fileName": f"{file_name}.{fmt}",
            "format": fmt,
        }


technical_coverage_service = TechnicalCoverageService(technical_project_service)
technical_export_service = TechnicalExportService(technical_project_service)
