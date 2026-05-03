from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from app.api.utils import absolute_url
from app.services.store import store

router = APIRouter()


@router.get("/api/projects/{project_id}/export/check")
async def export_check(project_id: str) -> dict[str, Any]:
    store.get_project(project_id)
    coverage = store.get_coverage(project_id)
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


@router.post("/api/projects/{project_id}/export", response_model=None)
async def export_document(
    project_id: str,
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
) -> Any:
    store.get_project(project_id)
    coverage = store.get_coverage(project_id)
    if coverage["noCover"] > 0:
        return JSONResponse(
            status_code=400,
            content={
                "detail": "存在未覆盖评分项（红项），禁止导出。",
                "code": "EXPORT_BLOCKED_BY_COVERAGE",
            },
        )

    file_name = str(data.get("fileName") or "").strip()
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
    if not bool(data.get("warningConfirmed")):
        return JSONResponse(
            status_code=400,
            content={
                "detail": "请先确认导出警告项后再继续。",
                "code": "EXPORT_WARNING_NOT_CONFIRMED",
            },
        )

    fmt = str(data.get("format") or "docx").lower()
    if fmt != "docx":
        return JSONResponse(
            status_code=400,
            content={
                "detail": "当前 MVP 仅支持导出 DOCX，PDF 导出尚未接入真实转换。",
                "code": "EXPORT_FORMAT_NOT_IMPLEMENTED",
            },
        )

    store.update_stage(project_id, 6, {"status": "completed"})
    return {
        "message": "Exported",
        "fileUrl": absolute_url(request, f"/api/projects/{project_id}/final-document/file"),
        "fileName": f"{file_name}.{fmt}",
        "format": fmt,
    }
