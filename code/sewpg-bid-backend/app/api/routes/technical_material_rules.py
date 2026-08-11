from __future__ import annotations

"""素材库「规则」tab 的技术标规则管理接口。

- 事实表清单（全局一份）：SQL 表为唯一事实来源，保存时重写 override JSON 作派生缓存；
  原表存档、_global 不可变版本等逻辑复用 technical_fact_spec_global。
- 附表填写规则（按客户一份）：SQL 表按 customer_id 存行，项目自动套用其所属客户的规则；
  旧 projectId 版端点保留兼容（GET 按项目客户解析元数据、POST 引导改用 customerName），
  但不再是消费来源。
"""

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response

from app.core.config import settings as app_settings
from app.services.auth_service import current_user
from app.services.identity import build_project_identity
from app.services.technical_appendix_source_matrix import (
    parse_appendix_source_matrix,
    source_terms,
)
from app.services.technical_fact_field_specs import load_specs
from app.services.technical_fact_spec_global import (
    global_fact_specs_archive_path,
    load_global_fact_specs_meta,
    save_global_fact_specs,
)
from app.services.technical_fact_spec_import import FactSpecImportError, import_specs
from app.services.technical_gap_repository import get_technical_gap_project_runtime_state
from app.services.technical_gap_service import technical_gap_service
from app.services.technical_rules_store import (
    appendix_rules_meta,
    export_appendix_rules_xlsx,
    export_fact_specs_xlsx,
    list_appendix_rules,
    list_fact_spec_rows,
    replace_appendix_rules,
    replace_fact_spec_rows,
    resolve_customer,
    store_imported_fact_spec_rows,
)

router = APIRouter()

# 附表规则 xlsx 在项目数据卷下的固定位置（旧 projectId 版下载端点留盘档案）
APPENDIX_SOURCE_MATRIX_RELATIVE_PATH = ("technical-workspace", "appendix-source-matrix.xlsx")

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _operator_name(user: dict[str, Any]) -> str:
    return str(user.get("name") or user.get("email") or user.get("id") or "")


def _xlsx_response(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _require_customer(customer_name: str | None) -> dict[str, Any]:
    """customerName query 参数 → canonical 客户身份；缺省/空白 400。"""
    name = str(customer_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="缺少 customerName 参数。")
    identity = resolve_customer(name)
    if not identity.get("customerId"):
        raise HTTPException(status_code=400, detail="客户名不能为空。")
    return identity


async def _appendix_meta_for_customer(identity: dict[str, Any]) -> dict[str, Any]:
    """客户规则元数据；无规则返回空 dict（前端据此切空态）。"""
    meta = await appendix_rules_meta(str(identity["customerId"]))
    if not meta:
        return {}
    return {
        **meta,
        "customerName": str(identity.get("customerCanonicalName") or identity.get("customerInput") or ""),
        "customerId": str(identity["customerId"]),
    }


# ---------------------------------------------------------------------------
# 事实表清单（全局）
# ---------------------------------------------------------------------------


@router.post("/api/technical/materials/rules/fact-specs")
async def upload_global_fact_specs(
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """上传全局事实表清单（.xlsx）：SQL 落库 + override 生效 + 原表存档 + _global 不可变版本。

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

    result = save_global_fact_specs(
        specs,
        file_name=filename,
        uploaded_by=_operator_name(user),
        content=content,
    )
    await store_imported_fact_spec_rows(specs, _operator_name(user))
    return result


@router.get("/api/technical/materials/rules/fact-specs")
async def get_global_fact_specs(_: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    """全局清单当前来源：SQL 已有记录返回 override 元数据，否则按历史 sidecar 展示。

    仓库不再自带默认清单（上游 283381f 收敛）：都没上传过时返回 source=none。
    历史 override（本次改造前上传、尚未入库）按原 sidecar 元数据展示。
    """
    specs = await list_fact_spec_rows()
    if specs:
        meta = load_global_fact_specs_meta() or {}
        return {
            "source": "override",
            "specTotal": len(specs),
            "fileName": str(meta.get("fileName") or ""),
            "uploadedAt": str(meta.get("uploadedAt") or ""),
            "uploadedBy": str(meta.get("uploadedBy") or ""),
        }
    meta = load_global_fact_specs_meta()
    if meta:
        return {"source": "override", **meta}
    return {"source": "none", "specTotal": 0}


@router.get("/api/technical/materials/rules/fact-specs/rows")
async def get_global_fact_spec_rows(_: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    """弹窗编辑数据：SQL 中的完整 spec 列表；未保存过时回落当前生效清单（默认/历史 override）。"""
    specs = await list_fact_spec_rows()
    if not specs:
        specs = list(load_specs())
    return {"specs": specs}


@router.put("/api/technical/materials/rules/fact-specs/rows")
async def save_global_fact_spec_rows(
    data: dict[str, Any],
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """弹窗整表保存：校验 key/label 非空后全量替换，并重写 override JSON 派生缓存。"""
    raw_specs = data.get("specs") if isinstance(data, dict) else None
    if not isinstance(raw_specs, list):
        raise HTTPException(status_code=400, detail="specs 必须是数组。")
    specs: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_specs, start=1):
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail=f"第 {index} 行不是有效对象。")
        if not str(raw.get("key") or "").strip():
            raise HTTPException(status_code=400, detail=f"第 {index} 行缺少 key（字段键）。")
        if not str(raw.get("label") or "").strip():
            raise HTTPException(status_code=400, detail=f"第 {index} 行缺少 label（字段名称）。")
        specs.append(dict(raw))
    return await replace_fact_spec_rows(specs, _operator_name(user))


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


@router.get("/api/technical/materials/rules/fact-specs/export")
async def export_global_fact_specs() -> Response:
    """导出当前生效清单为 xlsx（列头与导入解析器兼容，导出件可再导入）；无鉴权同 download。"""
    specs = await list_fact_spec_rows()
    if not specs:
        specs = list(load_specs())
    return _xlsx_response(export_fact_specs_xlsx(specs), "technical_fact_specs.xlsx")


# ---------------------------------------------------------------------------
# 附表填写规则（按客户）
# ---------------------------------------------------------------------------


@router.post("/api/technical/materials/rules/appendix-source-matrix")
async def upload_appendix_source_matrix_rule(
    customerName: str | None = Query(default=None),
    projectId: str | None = Query(default=None),
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """按客户上传附表填写规则：用现有解析器解析，只取属于该客户的行并全量替换。

    旧 projectId 版上传入口已废弃：规则改为按客户维护，项目自动套用所属客户的规则。
    """
    if projectId and not customerName:
        raise HTTPException(
            status_code=410,
            detail="附表填写规则已改为按客户维护，请改用 customerName 参数上传；项目会自动套用所属客户的规则。",
        )
    identity = _require_customer(customerName)
    filename = str(file.filename or "")
    if not filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="附表填写规则必须是 .xlsx 文件。")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空。")

    tmp_upload: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as handle:
            handle.write(content)
            tmp_upload = Path(handle.name)
        matrix = parse_appendix_source_matrix(tmp_upload)
    finally:
        if tmp_upload is not None:
            tmp_upload.unlink(missing_ok=True)
    rows = matrix.get("rows") if isinstance(matrix.get("rows"), list) else []
    if not rows:
        raise HTTPException(
            status_code=400,
            detail="未解析到有效规则行，请检查表头（客户/表格/项目定制/标准文件/其他）。",
        )
    customer_id = str(identity["customerId"])
    own_rows = [
        row
        for row in rows
        if str(resolve_customer(row.get("customer")).get("customerId") or "") == customer_id
    ]
    if not own_rows:
        raise HTTPException(
            status_code=400,
            detail=f"文件中没有属于客户「{identity.get('customerCanonicalName') or customerName}」的规则行。",
        )

    await replace_appendix_rules(
        customer_id,
        str(identity.get("customerCanonicalName") or customerName),
        own_rows,
        _operator_name(user),
        file_name=filename,
    )
    applied = await technical_gap_service.replay_appendix_source_matrix_for_customer(
        str(identity.get("customerCanonicalName") or customerName)
    )
    meta = await _appendix_meta_for_customer(identity)
    return {
        "rowCount": len(own_rows),
        "fileName": filename,
        "uploadedAt": str(meta.get("uploadedAt") or ""),
        "applied": applied,
    }


@router.get("/api/technical/materials/rules/appendix-source-matrix")
async def get_appendix_source_matrix_rule(
    customerName: str | None = Query(default=None),
    projectId: str | None = Query(default=None),
    _: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """客户附表填写规则元数据；无规则返回空 dict。

    兼容旧 projectId 调用：按项目所属客户解析（项目不存在仍 404）。
    """
    if customerName:
        return await _appendix_meta_for_customer(_require_customer(customerName))
    if projectId:
        project = get_technical_gap_project_runtime_state(projectId)
        identity = build_project_identity(project)
        return await _appendix_meta_for_customer(
            {
                "customerId": str(identity.get("customerId") or ""),
                "customerCanonicalName": str(
                    identity.get("customerCanonicalName") or identity.get("customerName") or ""
                ),
            }
        )
    raise HTTPException(status_code=400, detail="缺少 customerName 参数。")


@router.get("/api/technical/materials/rules/appendix-source-matrix/rows")
async def get_appendix_source_matrix_rows(
    customerName: str | None = Query(default=None),
    _: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """弹窗编辑数据：该客户的规则行（无 customer 列，保存时统一写入当前客户）。"""
    identity = _require_customer(customerName)
    rows = await list_appendix_rules(str(identity["customerId"]))
    return {"rows": rows}


@router.put("/api/technical/materials/rules/appendix-source-matrix/rows")
async def save_appendix_source_matrix_rows(
    data: dict[str, Any],
    customerName: str | None = Query(default=None),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """弹窗整表保存：全量替换该客户规则，随后重放到该客户已完成识别的项目。"""
    identity = _require_customer(customerName)
    raw_rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(raw_rows, list):
        raise HTTPException(status_code=400, detail="rows 必须是数组。")
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_rows, start=1):
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail=f"第 {index} 行不是有效对象。")
        if not str(raw.get("tableTitle") or "").strip():
            raise HTTPException(status_code=400, detail=f"第 {index} 行缺少「表格/附表」。")
        rows.append(
            {
                "tableTitle": str(raw.get("tableTitle") or "").strip(),
                "projectSources": source_terms(raw.get("projectSources")),
                "standardSources": source_terms(raw.get("standardSources")),
                "otherSources": source_terms(raw.get("otherSources")),
            }
        )
    customer_name = str(identity.get("customerCanonicalName") or customerName)
    result = await replace_appendix_rules(
        str(identity["customerId"]), customer_name, rows, _operator_name(user)
    )
    applied = await technical_gap_service.replay_appendix_source_matrix_for_customer(customer_name)
    return {**result, "applied": applied}


@router.get("/api/technical/materials/rules/appendix-source-matrix/export")
async def export_appendix_source_matrix_rule(
    customerName: str | None = Query(default=None),
) -> Response:
    """导出该客户附表规则为 xlsx（列头与解析器兼容，可再导入）；无鉴权同 download。"""
    identity = _require_customer(customerName)
    customer_id = str(identity["customerId"])
    rows = await list_appendix_rules(customer_id)
    if not rows:
        raise HTTPException(status_code=404, detail="该客户尚未维护附表填写规则。")
    customer_name = str(identity.get("customerCanonicalName") or customerName)
    content = export_appendix_rules_xlsx(customer_name, rows)
    return _xlsx_response(content, f"appendix_rules_{customer_id}.xlsx")


@router.get("/api/technical/materials/rules/appendix-source-matrix/download")
async def download_appendix_source_matrix_rule(
    projectId: str = Query(...),
) -> FileResponse:
    """下载项目附表填写规则 xlsx 留盘档案（旧 projectId 版）；不存在或尚未上传时 404。

    与 raw/wiki 等 content 下载端点一致不做 Header 鉴权：前端经 window.open 直连下载。
    """
    project = get_technical_gap_project_runtime_state(projectId)
    matrix_path = Path(app_settings.documents_dir) / projectId / Path(*APPENDIX_SOURCE_MATRIX_RELATIVE_PATH)
    if not matrix_path.is_file():
        raise HTTPException(status_code=404, detail="该项目尚未上传附表填写规则。")
    raw = project.get("technicalAppendixSourceMatrix") if isinstance(project, dict) else {}
    file_name = str((raw or {}).get("fileName") or "") if isinstance(raw, dict) else ""
    return FileResponse(matrix_path, filename=file_name or matrix_path.name)
