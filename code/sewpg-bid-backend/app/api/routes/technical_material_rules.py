from __future__ import annotations

"""素材库「规则」tab 的技术标规则管理接口。

- 事实表清单是全局系统默认规则：与设置页上传端点共用 override 逻辑，
  另存原表与元数据到 documents_dir/_config/，并固化 _global 不可变版本；
- 附表填写规则按项目维护：行为与项目级上传端点完全一致
  （内部复用 technical_gap_service.upload_appendix_source_matrix）。
"""

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.core.config import settings as app_settings
from app.services.auth_service import current_user
from app.services.technical_fact_field_specs import load_specs
from app.services.technical_fact_spec_global import (
    global_fact_specs_archive_path,
    load_global_fact_specs_meta,
    save_global_fact_specs,
)
from app.services.technical_fact_spec_import import FactSpecImportError, import_specs
from app.services.technical_gap_repository import get_technical_gap_project_runtime_state
from app.services.technical_gap_service import appendix_source_matrix_meta, technical_gap_service

router = APIRouter()

# 附表规则 xlsx 在项目数据卷下的固定位置（与 upload_appendix_source_matrix 写入路径一致）
APPENDIX_SOURCE_MATRIX_RELATIVE_PATH = ("technical-workspace", "appendix-source-matrix.xlsx")


def _operator_name(user: dict[str, Any]) -> str:
    return str(user.get("name") or user.get("email") or user.get("id") or "")


@router.post("/api/technical/materials/rules/fact-specs")
async def upload_global_fact_specs(
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """上传全局事实表清单（.xlsx）：override 生效 + 原表存档 + _global 不可变版本。

    契约与设置页端点一致（multipart 单文件字段 file），返回额外带 fileName/uploadedAt。
    """
    filename = str(file.filename or "")
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="填表规则清单必须是 .xlsx 文件。")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空。")

    tmp_upload: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as handle:
            handle.write(content)
            tmp_upload = Path(handle.name)
        specs = import_specs(tmp_upload)
    except FactSpecImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if tmp_upload is not None:
            tmp_upload.unlink(missing_ok=True)

    return save_global_fact_specs(
        specs,
        file_name=filename,
        uploaded_by=_operator_name(user),
        content=content,
    )


@router.get("/api/technical/materials/rules/fact-specs")
async def get_global_fact_specs(_: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    """全局清单当前来源：已上传 override 返回其元数据，否则回落仓库默认清单。"""
    meta = load_global_fact_specs_meta()
    if meta:
        return {"source": "override", **meta}
    return {"source": "repo-default", "specTotal": len(load_specs())}


@router.get("/api/technical/materials/rules/fact-specs/download")
async def download_global_fact_specs() -> FileResponse:
    """下载全局清单原始 xlsx 存档；尚未上传时 404。

    与 raw/wiki 等 content 下载端点一致不做 Header 鉴权：前端经 window.open 直连下载。
    """
    archive_path = global_fact_specs_archive_path()
    if not archive_path.is_file():
        raise HTTPException(status_code=404, detail="尚未上传全局事实表清单。")
    meta = load_global_fact_specs_meta() or {}
    return FileResponse(archive_path, filename=str(meta.get("fileName") or archive_path.name))


@router.post("/api/technical/materials/rules/appendix-source-matrix")
async def upload_appendix_source_matrix_rule(
    projectId: str = Query(...),
    file: UploadFile = File(...),
    _: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """按项目上传附表填写规则：行为与项目级上传端点一致（项目不存在时 404）。"""
    return await technical_gap_service.upload_appendix_source_matrix(
        projectId, str(file.filename or ""), await file.read()
    )


@router.get("/api/technical/materials/rules/appendix-source-matrix")
async def get_appendix_source_matrix_rule(
    projectId: str = Query(...),
    _: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """项目附表填写规则元数据；项目不存在 404，未上传时返回空 dict。"""
    project = get_technical_gap_project_runtime_state(projectId)
    return appendix_source_matrix_meta(project)


@router.get("/api/technical/materials/rules/appendix-source-matrix/download")
async def download_appendix_source_matrix_rule(
    projectId: str = Query(...),
) -> FileResponse:
    """下载项目附表填写规则 xlsx；项目不存在或尚未上传时 404。

    与 raw/wiki 等 content 下载端点一致不做 Header 鉴权：前端经 window.open 直连下载。
    """
    project = get_technical_gap_project_runtime_state(projectId)
    matrix_path = Path(app_settings.documents_dir) / projectId / Path(*APPENDIX_SOURCE_MATRIX_RELATIVE_PATH)
    if not matrix_path.is_file():
        raise HTTPException(status_code=404, detail="该项目尚未上传附表填写规则。")
    meta = appendix_source_matrix_meta(project)
    return FileResponse(matrix_path, filename=str(meta.get("fileName") or matrix_path.name))
