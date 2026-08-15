from __future__ import annotations

import hashlib
import json
import logging
# 模块符号保留：facade re-export，既有测试经本模块 patch shutil.which /
# subprocess.run（作用于共享 stdlib 模块对象，对 performance_contract_docx 内调用同样生效）。
import shutil
import subprocess
from pathlib import Path
from typing import Any

from sqlalchemy import bindparam, text

from app.core.config import settings
from app.models import async_session
from app.services.material_runtime_tables import ensure_material_runtime_tables
from app.services.material_tags import normalize_material_tags
from app.services.minio_client import minio_client
from app.services.peripheral import PeripheralError
from app.services.file_utils import safe_filename
# 拆分搬迁：合同 docx 处理实现已移至 performance_contract_docx，
# 此处 re-export 保持 app.services.performance_package_service.<符号> 可解析、可 patch。
from app.services.performance_contract_docx import (
    A_NAMESPACE,
    CONTRACT_OUTPUT_EAST_ASIA_FONT,
    CONTRACT_OUTPUT_SYMBOL_FONT,
    CONTRACT_OUTPUT_WESTERN_FONT,
    MC_NAMESPACE,
    OOXML_NAMESPACES,
    PIC_NAMESPACE,
    RELATIONSHIP_NAMESPACE,
    THEME_EAST_ASIA_SCRIPTS,
    WORD_NAMESPACE,
    WP_NAMESPACE,
    _append_ooxml_child,
    _block_has_page_break,
    _block_kind,
    _block_text,
    _clean_contract_output_title,
    _contract_content_blocks,
    _contract_font_table_xml,
    _contract_item_file_name,
    _contract_match_score,
    _contract_title_indexes_from_page_breaks,
    _copy_related_parts,
    _dedupe_repeated_title,
    _docx_blocks_to_bytes,
    _first_meaningful_block_text,
    _has_drawings,
    _has_ooxml_ancestor,
    _insert_ooxml_child,
    _is_contract_table_caption_row,
    _is_contract_title_block,
    _is_empty_page_break_paragraph,
    _is_layout_only_paragraph,
    _longest_common_substring_length,
    _match_text,
    _match_tokens,
    _normalize_contract_block_format,
    _normalize_contract_docx_with_soffice,
    _normalize_layout_paragraph_spacing,
    _ordered_character_coverage,
    _sanitize_contract_drawingml,
    _sanitize_contract_docx_fonts,
    _sanitize_contract_settings_xml,
    _sanitize_mc_ignorable,
    _sanitize_theme_fonts_xml,
    _sanitize_word_fonts_xml,
    _serialize_ooxml,
    _set_ooxml_rfonts,
    _set_row_cant_split,
    _set_row_keep_next,
    _stabilize_contract_table_pagination,
    _trim_leading_layout_blocks,
    _trim_trailing_layout_blocks,
    _without_private_keys,
    ensure_contract_docx_file_name,
    match_contract_chunks_to_items,
    render_contract_item_docx,
    split_performance_contract_docx,
)
# 拆分搬迁：汇总表解析/字段推断实现已移至 performance_summary_parse，门面 re-export。
from app.services.performance_summary_parse import (
    PERFORMANCE_ITEM_EDITABLE_TEXT_FIELDS,
    PERFORMANCE_ITEM_EDITABLE_YEAR_FIELDS,
    PERFORMANCE_ITEM_ROW_VALUE_REPAIR_FIELDS,
    PERFORMANCE_ITEM_ROW_VALUE_TEXT_FIELDS,
    PERFORMANCE_ITEM_ROW_VALUE_YEAR_FIELDS,
    _clean_text,
    _core_values,
    _extract_year,
    _field_key,
    _field_schema_item,
    _find_header_row,
    _first_value,
    _header_score,
    _infer_category_name,
    _infer_power_rating,
    _infer_scene,
    _infer_summary,
    _is_data_row,
    _normalize_empty,
    _parse_item_year,
    _parse_year_filter,
    _replace_row_value_year,
    _row_value_update_key,
    _select_summary_table,
    _split_turbine_models,
    _sync_performance_item_row_values,
    _table_to_rows,
    _time_facts,
    _unique_headers,
    _unique_ints,
    _value_by_header,
    parse_performance_summary_docx,
)


PERFORMANCE_CATEGORY_SCOPES = {"standard", "customer", "project"}
PERFORMANCE_CATEGORY_REVIEW_STATUSES = {"draft", "reviewed", "disabled"}
PERFORMANCE_CATEGORY_STATUSES = {"enabled", "disabled"}
SUMMARY_ATTACHMENT_TYPE = "summary_table"
CONTRACT_ATTACHMENT_TYPE = "contract_bundle"
ITEM_CONTRACT_ATTACHMENT_TYPE = "contract_item"
DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ITEM_CONTRACT_FORMAT_VERSION = 15
logger = logging.getLogger(__name__)


class PerformancePackageService:
    async def list_categories(
        self,
        *,
        keyword: str = "",
        scene: str = "",
        power_rating: str = "",
        turbine_model: str = "",
        time_keyword: str = "",
        contract_year: str = "",
        delivery_year: str = "",
        operation_year: str = "",
        tag: str = "",
        status: str = "enabled",
        sort_by: str = "updatedAt",
        sort_order: str = "desc",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        current_page = max(1, int(page or 1))
        current_page_size = max(1, min(100, int(page_size or 20)))
        offset = (current_page - 1) * current_page_size
        filters, params = self._category_filters(
            keyword=keyword,
            scene=scene,
            power_rating=power_rating,
            turbine_model=turbine_model,
            time_keyword=time_keyword,
            contract_year=contract_year,
            delivery_year=delivery_year,
            operation_year=operation_year,
            tag=tag,
            status=status,
        )
        where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
        order_sql = _category_order_sql(sort_by, sort_order)
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            await self._backfill_derived_item_fields(session)
            total_result = await session.execute(
                text(f"SELECT COUNT(*) FROM performance_categories c {where_sql}"),
                params,
            )
            total = int(total_result.scalar_one() or 0)
            rows = await session.execute(
                text(
                    f"""
                    SELECT
                        c.*,
                        (SELECT COUNT(*) FROM performance_items i WHERE i.category_id = c.id) AS item_count,
                        (
                            SELECT COALESCE(jsonb_agg(DISTINCT model_value ORDER BY model_value), '[]'::jsonb)
                            FROM performance_items i
                            CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(i.turbine_models, '[]'::jsonb)) AS model_value
                            WHERE i.category_id = c.id AND model_value <> ''
                        ) AS turbine_models,
                        (
                            SELECT COALESCE(jsonb_agg(DISTINCT i.contract_year ORDER BY i.contract_year), '[]'::jsonb)
                            FROM performance_items i
                            WHERE i.category_id = c.id AND i.contract_year IS NOT NULL
                        ) AS contract_years,
                        (
                            SELECT COALESCE(jsonb_agg(DISTINCT i.delivery_year ORDER BY i.delivery_year), '[]'::jsonb)
                            FROM performance_items i
                            WHERE i.category_id = c.id AND i.delivery_year IS NOT NULL
                        ) AS delivery_years,
                        (
                            SELECT COALESCE(jsonb_agg(DISTINCT i.operation_year ORDER BY i.operation_year), '[]'::jsonb)
                            FROM performance_items i
                            WHERE i.category_id = c.id AND i.operation_year IS NOT NULL
                        ) AS operation_years,
                        (SELECT COUNT(*) FROM performance_attachments a WHERE a.category_id = c.id) AS attachment_count,
                        (
                            SELECT COUNT(*)
                            FROM performance_attachments a
                            WHERE a.category_id = c.id AND a.attachment_type = :contract_attachment_type
                        ) AS contract_attachment_count,
                        (
                            SELECT COUNT(*)
                            FROM performance_item_attachments ia
                            WHERE ia.category_id = c.id AND ia.attachment_type = :item_contract_attachment_type
                        ) AS item_contract_attachment_count,
                        (
                            SELECT a.file_name
                            FROM performance_attachments a
                            WHERE a.category_id = c.id AND a.attachment_type = :summary_attachment_type
                            ORDER BY a.id DESC
                            LIMIT 1
                        ) AS summary_file_name,
                        (
                            SELECT a.file_name
                            FROM performance_attachments a
                            WHERE a.category_id = c.id AND a.attachment_type = :contract_attachment_type
                            ORDER BY a.id DESC
                            LIMIT 1
                        ) AS contract_file_name
                    FROM performance_categories c
                    {where_sql}
                    {order_sql}
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {
                    **params,
                    "limit": current_page_size,
                    "offset": offset,
                    "summary_attachment_type": SUMMARY_ATTACHMENT_TYPE,
                    "contract_attachment_type": CONTRACT_ATTACHMENT_TYPE,
                    "item_contract_attachment_type": ITEM_CONTRACT_ATTACHMENT_TYPE,
                },
            )
        return {
            "items": [self._category_row_to_dict(row._mapping) for row in rows],
            "total": total,
            "page": current_page,
            "pageSize": current_page_size,
        }

    async def list_items(
        self,
        *,
        keyword: str = "",
        turbine_model: str = "",
        time_keyword: str = "",
        contract_year: str = "",
        delivery_year: str = "",
        operation_year: str = "",
        category_id: str = "",
        status: str = "enabled",
        sort_by: str = "updatedAt",
        sort_order: str = "desc",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        current_page = max(1, int(page or 1))
        current_page_size = max(1, min(100, int(page_size or 20)))
        offset = (current_page - 1) * current_page_size
        filters, params = self._item_filters(
            keyword=keyword,
            turbine_model=turbine_model,
            time_keyword=time_keyword,
            contract_year=contract_year,
            delivery_year=delivery_year,
            operation_year=operation_year,
            category_id=category_id,
            status=status,
        )
        where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
        order_sql = _item_order_sql(sort_by, sort_order)
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            await self._backfill_derived_item_fields(session)
            total_result = await session.execute(
                text(
                    f"""
                    SELECT COUNT(*)
                    FROM performance_items i
                    JOIN performance_categories c ON c.id = i.category_id
                    {where_sql}
                    """
                ),
                params,
            )
            total = int(total_result.scalar_one() or 0)
            rows = await session.execute(
                text(
                    f"""
                    SELECT
                        i.*,
                        c.name AS category_name,
                        COALESCE(c.status, CASE WHEN c.review_status = 'disabled' THEN 'disabled' ELSE 'enabled' END) AS category_status
                    FROM performance_items i
                    JOIN performance_categories c ON c.id = i.category_id
                    {where_sql}
                    {order_sql}
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {**params, "limit": current_page_size, "offset": offset},
            )
            item_payload: list[dict[str, Any]] = []
            numeric_ids: list[int] = []
            for row in rows:
                row_dict = self._item_row_to_dict(row._mapping)
                row_dict["categoryName"] = row._mapping.get("category_name") or ""
                row_dict["categoryStatus"] = row._mapping.get("category_status") or "enabled"
                row_dict["attachments"] = []
                item_payload.append(row_dict)
                numeric_ids.append(int(row._mapping.get("id") or 0))
            if numeric_ids:
                attachment_rows = await session.execute(
                    text(
                        """
                        SELECT *
                        FROM performance_item_attachments
                        WHERE item_id IN :item_ids
                        ORDER BY item_id ASC, created_at DESC, id DESC
                        """
                    ).bindparams(bindparam("item_ids", expanding=True)),
                    {"item_ids": numeric_ids},
                )
                attachments_by_item: dict[int, list[dict[str, Any]]] = {}
                for row in attachment_rows:
                    attachments_by_item.setdefault(int(row._mapping.get("item_id") or 0), []).append(
                        self._item_attachment_row_to_dict(row._mapping)
                    )
                for row_dict, numeric_item_id in zip(item_payload, numeric_ids):
                    row_dict["attachments"] = attachments_by_item.get(numeric_item_id, [])
        return {
            "items": item_payload,
            "total": total,
            "page": current_page,
            "pageSize": current_page_size,
        }

    def _item_filters(
        self,
        *,
        keyword: str,
        turbine_model: str,
        time_keyword: str,
        contract_year: str,
        delivery_year: str,
        operation_year: str,
        category_id: str,
        status: str,
    ) -> tuple[list[str], dict[str, Any]]:
        filters: list[str] = []
        params: dict[str, Any] = {}
        selected_status = str(status or "").strip()
        if selected_status in PERFORMANCE_CATEGORY_STATUSES:
            filters.append("COALESCE(c.status, CASE WHEN c.review_status = 'disabled' THEN 'disabled' ELSE 'enabled' END) = :status")
            params["status"] = selected_status
        kw = str(keyword or "").strip()
        if kw:
            filters.append(
                "("
                "i.project_name ILIKE :keyword OR i.customer_name ILIKE :keyword OR "
                "i.partner_name ILIKE :keyword OR "
                "i.turbine_model ILIKE :keyword OR i.row_values::text ILIKE :keyword OR "
                "c.name ILIKE :keyword"
                ")"
            )
            params["keyword"] = f"%{kw}%"
        selected_model = str(turbine_model or "").strip()
        if selected_model:
            filters.append(
                "(i.turbine_model ILIKE :turbine_model OR i.turbine_models::text ILIKE :turbine_model OR i.row_values::text ILIKE :turbine_model)"
            )
            params["turbine_model"] = f"%{selected_model}%"
        selected_time = str(time_keyword or "").strip()
        if selected_time:
            filters.append(
                "(i.delivery_or_operation_time ILIKE :time_keyword OR i.time_facts::text ILIKE :time_keyword OR i.row_values::text ILIKE :time_keyword)"
            )
            params["time_keyword"] = f"%{selected_time}%"
        contract_year_value = _parse_year_filter(contract_year)
        if contract_year_value is not None:
            filters.append("i.contract_year = :contract_year")
            params["contract_year"] = contract_year_value
        delivery_year_value = _parse_year_filter(delivery_year)
        if delivery_year_value is not None:
            filters.append("i.delivery_year = :delivery_year")
            params["delivery_year"] = delivery_year_value
        operation_year_value = _parse_year_filter(operation_year)
        if operation_year_value is not None:
            filters.append("i.operation_year = :operation_year")
            params["operation_year"] = operation_year_value
        selected_category = str(category_id or "").strip()
        if selected_category:
            filters.append("i.category_id = :category_id")
            params["category_id"] = self._numeric_category_id(selected_category)
        return filters, params

    async def get_category(self, category_id: str) -> dict[str, Any]:
        numeric_id = self._numeric_category_id(category_id)
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            await self._backfill_derived_item_fields(session, category_id=numeric_id)
            await self._ensure_contract_item_attachments(session, category_id=numeric_id)
            category_result = await session.execute(
                text(
                        """
                    SELECT
                        c.*,
                        (SELECT COUNT(*) FROM performance_items i WHERE i.category_id = c.id) AS item_count,
                        (
                            SELECT COALESCE(jsonb_agg(DISTINCT model_value ORDER BY model_value), '[]'::jsonb)
                            FROM performance_items i
                            CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(i.turbine_models, '[]'::jsonb)) AS model_value
                            WHERE i.category_id = c.id AND model_value <> ''
                        ) AS turbine_models,
                        (
                            SELECT COALESCE(jsonb_agg(DISTINCT i.contract_year ORDER BY i.contract_year), '[]'::jsonb)
                            FROM performance_items i
                            WHERE i.category_id = c.id AND i.contract_year IS NOT NULL
                        ) AS contract_years,
                        (
                            SELECT COALESCE(jsonb_agg(DISTINCT i.delivery_year ORDER BY i.delivery_year), '[]'::jsonb)
                            FROM performance_items i
                            WHERE i.category_id = c.id AND i.delivery_year IS NOT NULL
                        ) AS delivery_years,
                        (
                            SELECT COALESCE(jsonb_agg(DISTINCT i.operation_year ORDER BY i.operation_year), '[]'::jsonb)
                            FROM performance_items i
                            WHERE i.category_id = c.id AND i.operation_year IS NOT NULL
                        ) AS operation_years,
                        (SELECT COUNT(*) FROM performance_attachments a WHERE a.category_id = c.id) AS attachment_count,
                        (
                            SELECT COUNT(*)
                            FROM performance_attachments a
                            WHERE a.category_id = c.id AND a.attachment_type = :contract_attachment_type
                        ) AS contract_attachment_count,
                        (
                            SELECT COUNT(*)
                            FROM performance_item_attachments ia
                            WHERE ia.category_id = c.id AND ia.attachment_type = :item_contract_attachment_type
                        ) AS item_contract_attachment_count,
                        (
                            SELECT a.file_name
                            FROM performance_attachments a
                            WHERE a.category_id = c.id AND a.attachment_type = :summary_attachment_type
                            ORDER BY a.id DESC
                            LIMIT 1
                        ) AS summary_file_name,
                        (
                            SELECT a.file_name
                            FROM performance_attachments a
                            WHERE a.category_id = c.id AND a.attachment_type = :contract_attachment_type
                            ORDER BY a.id DESC
                            LIMIT 1
                        ) AS contract_file_name
                    FROM performance_categories c
                    WHERE c.id = :id
                    """
                ),
                {
                    "id": numeric_id,
                    "summary_attachment_type": SUMMARY_ATTACHMENT_TYPE,
                    "contract_attachment_type": CONTRACT_ATTACHMENT_TYPE,
                    "item_contract_attachment_type": ITEM_CONTRACT_ATTACHMENT_TYPE,
                },
            )
            category_row = category_result.first()
            if category_row is None:
                raise PeripheralError(404, "业绩类别不存在。", "PERFORMANCE_CATEGORY_NOT_FOUND")
            item_rows = await session.execute(
                text(
                    """
                    SELECT *
                    FROM performance_items
                    WHERE category_id = :id
                    ORDER BY row_index ASC, id ASC
                    """
                ),
                {"id": numeric_id},
            )
            attachment_rows = await session.execute(
                text(
                    """
                    SELECT *
                    FROM performance_attachments
                    WHERE category_id = :id
                    ORDER BY created_at DESC, id DESC
                    """
                ),
                {"id": numeric_id},
            )
            item_attachment_rows = await session.execute(
                text(
                    """
                    SELECT *
                    FROM performance_item_attachments
                    WHERE category_id = :id
                    ORDER BY item_id ASC, created_at DESC, id DESC
                    """
                ),
                {"id": numeric_id},
            )
            item_attachments: dict[int, list[dict[str, Any]]] = {}
            for row in item_attachment_rows:
                item_attachments.setdefault(int(row._mapping.get("item_id") or 0), []).append(self._item_attachment_row_to_dict(row._mapping))
            item_payload = []
            for row in item_rows:
                row_dict = self._item_row_to_dict(row._mapping)
                row_dict["attachments"] = item_attachments.get(int(row._mapping.get("id") or 0), [])
                item_payload.append(row_dict)
        return {
            "item": self._category_row_to_dict(category_row._mapping),
            "rows": item_payload,
            "attachments": [self._attachment_row_to_dict(row._mapping) for row in attachment_rows],
        }

    async def preview_summary(self, upload: Any) -> dict[str, Any]:
        content, file_name, _mime_type = await _read_upload(upload)
        parsed = parse_performance_summary_docx(content, file_name=file_name)
        return {"message": "业绩汇总表解析完成", "preview": parsed}

    async def import_summary(
        self,
        upload: Any,
        *,
        contract_uploads: list[Any] | None = None,
        category_name: str = "",
        scene: str = "",
        power_rating: str = "",
        tags: Any = None,
        scope: str = "standard",
        review_status: str = "draft",
    ) -> dict[str, Any]:
        content, file_name, mime_type = await _read_upload(upload)
        contract_files: list[tuple[bytes, str, str]] = []
        for contract_upload in contract_uploads or []:
            contract_files.append(await _read_upload(contract_upload))
        if not contract_files:
            raise PeripheralError(
                400,
                "请同时上传合同附件：汇总表与合同需一次导入，不能拆开提交。",
                "PERFORMANCE_CONTRACT_FILES_REQUIRED",
            )
        for _contract_content, contract_file_name, _contract_mime_type in contract_files:
            ensure_contract_docx_file_name(contract_file_name)
        parsed = parse_performance_summary_docx(content, file_name=file_name)
        category_name = str(category_name or parsed.get("categoryName") or Path(file_name).stem).strip()
        if not category_name:
            raise PeripheralError(400, "业绩类别名称不能为空。", "PERFORMANCE_CATEGORY_NAME_REQUIRED")
        selected_scene = str(scene or parsed.get("scene") or "").strip()
        selected_power_rating = str(power_rating or parsed.get("powerRating") or "").strip()
        selected_scope = scope if scope in PERFORMANCE_CATEGORY_SCOPES else "standard"
        selected_review_status = review_status if review_status in PERFORMANCE_CATEGORY_REVIEW_STATUSES else "draft"
        normalized_tags = normalize_material_tags(tags)

        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            category_result = await session.execute(
                text(
                    """
                    INSERT INTO performance_categories (
                        name, scene, power_rating, summary, field_schema, tags, scope, review_status
                    )
                    VALUES (
                        :name, :scene, :power_rating, :summary, CAST(:field_schema AS JSONB),
                        CAST(:tags AS JSONB), :scope, :review_status
                    )
                    RETURNING *
                    """
                ),
                {
                    "name": category_name,
                    "scene": selected_scene,
                    "power_rating": selected_power_rating,
                    "summary": str(parsed.get("summary") or ""),
                    "field_schema": _json(parsed.get("fieldSchema") or []),
                    "tags": _json(normalized_tags),
                    "scope": selected_scope,
                    "review_status": selected_review_status,
                },
            )
            category_row = category_result.first()
            if category_row is None:
                raise PeripheralError(500, "业绩类别创建失败。", "PERFORMANCE_CATEGORY_CREATE_FAILED")
            numeric_id = int(category_row._mapping["id"])
            if parsed.get("rows"):
                await session.execute(
                    text(
                        """
                        INSERT INTO performance_items (
                            category_id, row_index, project_name, customer_name, partner_name, turbine_model,
                            turbine_models,
                            contract_quantity, trial_operation_quantity, commissioned_capacity_mw,
                            delivery_or_operation_time, contract_year, delivery_year, operation_year,
                            time_facts, contact_info, row_values
                        )
                        VALUES (
                            :category_id, :row_index, :project_name, :customer_name, :partner_name, :turbine_model,
                            CAST(:turbine_models AS JSONB),
                            :contract_quantity, :trial_operation_quantity, :commissioned_capacity_mw,
                            :delivery_or_operation_time, :contract_year, :delivery_year, :operation_year,
                            CAST(:time_facts AS JSONB), :contact_info, CAST(:row_values AS JSONB)
                        )
                        """
                    ),
                    [
                        {
                            "category_id": numeric_id,
                            "row_index": int(row.get("rowIndex") or index + 1),
                            "project_name": row.get("projectName") or "",
                            "customer_name": row.get("customerName") or "",
                            "partner_name": row.get("partnerName") or "",
                            "turbine_model": row.get("turbineModel") or "",
                            "turbine_models": _json(row.get("turbineModels") or []),
                            "contract_quantity": row.get("contractQuantity") or "",
                            "trial_operation_quantity": row.get("trialOperationQuantity") or "",
                            "commissioned_capacity_mw": row.get("commissionedCapacityMw") or "",
                            "delivery_or_operation_time": row.get("deliveryOrOperationTime") or "",
                            "contract_year": row.get("contractYear"),
                            "delivery_year": row.get("deliveryYear"),
                            "operation_year": row.get("operationYear"),
                            "time_facts": _json(row.get("timeFacts") or {}),
                            "contact_info": row.get("contactInfo") or "",
                            "row_values": _json(row.get("values") or {}),
                        }
                        for index, row in enumerate(parsed.get("rows") or [])
                    ],
                )

            bucket = settings.minio_buckets["materials"]
            object_key = f"performance-categories/PERCAT-{numeric_id:04d}/summary/{safe_filename(file_name, "performance.docx")}"
            uploaded_objects: list[tuple[str, str]] = []
            try:
                minio_client.put_object(bucket, object_key, content, content_type=mime_type)
                uploaded_objects.append((bucket, object_key))
                await session.execute(
                    text(
                        """
                        INSERT INTO performance_attachments (
                            category_id, attachment_type, file_name, minio_key, minio_bucket,
                            mime_type, size_bytes
                        )
                        VALUES (
                            :category_id, :attachment_type, :file_name, :minio_key, :minio_bucket,
                            :mime_type, :size_bytes
                        )
                        """
                    ),
                    {
                        "category_id": numeric_id,
                        "attachment_type": SUMMARY_ATTACHMENT_TYPE,
                        "file_name": file_name,
                        "minio_key": object_key,
                        "minio_bucket": bucket,
                        "mime_type": mime_type,
                        "size_bytes": len(content),
                    },
                )
                for contract_index, (contract_content, contract_file_name, contract_mime_type) in enumerate(contract_files):
                    contract_object_key = (
                        f"performance-categories/PERCAT-{numeric_id:04d}/{CONTRACT_ATTACHMENT_TYPE}/"
                        f"{contract_index + 1:02d}-{safe_filename(contract_file_name, "performance.docx")}"
                    )
                    minio_client.put_object(bucket, contract_object_key, contract_content, content_type=contract_mime_type)
                    uploaded_objects.append((bucket, contract_object_key))
                    contract_attachment_result = await session.execute(
                        text(
                            """
                            INSERT INTO performance_attachments (
                                category_id, attachment_type, file_name, minio_key, minio_bucket,
                                mime_type, size_bytes
                            )
                            VALUES (
                                :category_id, :attachment_type, :file_name, :minio_key, :minio_bucket,
                                :mime_type, :size_bytes
                            )
                            RETURNING id
                            """
                        ),
                        {
                            "category_id": numeric_id,
                            "attachment_type": CONTRACT_ATTACHMENT_TYPE,
                            "file_name": contract_file_name,
                            "minio_key": contract_object_key,
                            "minio_bucket": bucket,
                            "mime_type": contract_mime_type,
                            "size_bytes": len(contract_content),
                        },
                    )
                    contract_attachment_row = contract_attachment_result.first()
                    if contract_attachment_row is None:
                        raise PeripheralError(500, "业绩合同附件保存失败。", "PERFORMANCE_ATTACHMENT_CREATE_FAILED")
                    uploaded_objects.extend(
                        await self._replace_contract_item_attachments_for_source(
                            session,
                            category_id=numeric_id,
                            source_attachment_id=int(contract_attachment_row._mapping["id"]),
                            content=contract_content,
                            source_file_name=contract_file_name,
                        )
                    )
                await session.commit()
            except Exception:
                for uploaded_bucket, uploaded_key in uploaded_objects:
                    try:
                        minio_client.remove_object(uploaded_bucket, uploaded_key)
                    except Exception as exc:  # pragma: no cover - cleanup should not mask original error
                        logger.warning("Failed to remove performance import object %s/%s: %s", uploaded_bucket, uploaded_key, exc)
                raise
        return {
            "message": "业绩包已导入",
            "item": await self.get_category(f"PERCAT-{numeric_id:04d}"),
        }

    async def upload_attachment(
        self,
        category_id: str,
        upload: Any,
        *,
        attachment_type: str = CONTRACT_ATTACHMENT_TYPE,
    ) -> dict[str, Any]:
        numeric_id = self._numeric_category_id(category_id)
        content, file_name, mime_type = await _read_upload(upload)
        normalized_type = str(attachment_type or CONTRACT_ATTACHMENT_TYPE).strip() or CONTRACT_ATTACHMENT_TYPE
        if normalized_type not in {SUMMARY_ATTACHMENT_TYPE, CONTRACT_ATTACHMENT_TYPE, "other"}:
            normalized_type = "other"
        if normalized_type == CONTRACT_ATTACHMENT_TYPE:
            ensure_contract_docx_file_name(file_name)
        object_key = f"performance-categories/PERCAT-{numeric_id:04d}/{normalized_type}/{safe_filename(file_name, "performance.docx")}"
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            category_result = await session.execute(
                text("SELECT id FROM performance_categories WHERE id = :id"),
                {"id": numeric_id},
            )
            if category_result.first() is None:
                raise PeripheralError(404, "业绩类别不存在。", "PERFORMANCE_CATEGORY_NOT_FOUND")
            uploaded_child_objects: list[tuple[str, str]] = []
            try:
                minio_client.put_object(
                    settings.minio_buckets["materials"],
                    object_key,
                    content,
                    content_type=mime_type,
                )
                attachment_result = await session.execute(
                    text(
                        """
                        INSERT INTO performance_attachments (
                            category_id, attachment_type, file_name, minio_key, minio_bucket,
                            mime_type, size_bytes
                        )
                        VALUES (
                            :category_id, :attachment_type, :file_name, :minio_key, :minio_bucket,
                            :mime_type, :size_bytes
                        )
                        RETURNING *
                        """
                    ),
                    {
                        "category_id": numeric_id,
                        "attachment_type": normalized_type,
                        "file_name": file_name,
                        "minio_key": object_key,
                        "minio_bucket": settings.minio_buckets["materials"],
                        "mime_type": mime_type,
                        "size_bytes": len(content),
                    },
                )
                attachment_row = attachment_result.first()
                if attachment_row is None:
                    raise PeripheralError(500, "业绩附件保存失败。", "PERFORMANCE_ATTACHMENT_CREATE_FAILED")
                if normalized_type == CONTRACT_ATTACHMENT_TYPE:
                    uploaded_child_objects = await self._replace_contract_item_attachments_for_source(
                        session,
                        category_id=numeric_id,
                        source_attachment_id=int(attachment_row._mapping["id"]),
                        content=content,
                        source_file_name=file_name,
                    )
                await session.execute(
                    text("UPDATE performance_categories SET updated_at = NOW() WHERE id = :id"),
                    {"id": numeric_id},
                )
                await session.commit()
            except Exception:
                minio_client.remove_object(settings.minio_buckets["materials"], object_key)
                for bucket, key in uploaded_child_objects:
                    try:
                        minio_client.remove_object(bucket, key)
                    except Exception as exc:  # pragma: no cover - cleanup should not mask original error
                        logger.warning("Failed to remove split performance contract object %s/%s: %s", bucket, key, exc)
                raise
        return {"message": "业绩附件已上传", "item": await self.get_category(category_id)}

    async def download_attachment(self, category_id: str, attachment_id: str) -> dict[str, Any]:
        numeric_category_id = self._numeric_category_id(category_id)
        numeric_attachment_id = self._numeric_attachment_id(attachment_id)
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            result = await session.execute(
                text(
                    """
                    SELECT *
                    FROM performance_attachments
                    WHERE id = :attachment_id AND category_id = :category_id
                    """
                ),
                {"attachment_id": numeric_attachment_id, "category_id": numeric_category_id},
            )
            row = result.first()
        if row is None:
            raise PeripheralError(404, "业绩附件不存在。", "PERFORMANCE_ATTACHMENT_NOT_FOUND")
        item = self._attachment_row_to_dict(row._mapping)
        return {
            "bucket": item.get("minioBucket") or settings.minio_buckets["materials"],
            "key": item.get("minioKey") or "",
            "fileName": item.get("fileName") or f"{item['id']}.docx",
            "mimeType": item.get("mimeType") or "application/octet-stream",
            "attachmentType": item.get("attachmentType") or "",
            "sizeBytes": int(item.get("sizeBytes") or 0),
        }

    async def preview_attachment(
        self,
        category_id: str,
        attachment_id: str,
        *,
        browser_base_url: str = "",
        onlyoffice_base_url: str = "",
    ) -> dict[str, Any]:
        payload = await self.download_attachment(category_id, attachment_id)
        file_name = str(payload.get("fileName") or f"{attachment_id}.docx")
        file_path = f"/api/materials/performance/categories/{category_id}/attachments/{attachment_id}"
        return self._preview_payload(
            attachment_id=attachment_id,
            file_name=file_name,
            file_path=file_path,
            minio_key=str(payload.get("key") or ""),
            browser_base_url=browser_base_url,
            onlyoffice_base_url=onlyoffice_base_url,
        )

    async def download_item_attachment(self, category_id: str, item_id: str, attachment_id: str) -> dict[str, Any]:
        numeric_category_id = self._numeric_category_id(category_id)
        numeric_item_id = self._numeric_item_id(item_id)
        numeric_attachment_id = self._numeric_item_attachment_id(attachment_id)
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            result = await session.execute(
                text(
                    """
                    SELECT *
                    FROM performance_item_attachments
                    WHERE id = :attachment_id
                      AND item_id = :item_id
                      AND category_id = :category_id
                    """
                ),
                {
                    "attachment_id": numeric_attachment_id,
                    "item_id": numeric_item_id,
                    "category_id": numeric_category_id,
                },
            )
            row = result.first()
        if row is None:
            raise PeripheralError(404, "项目合同附件不存在。", "PERFORMANCE_ITEM_ATTACHMENT_NOT_FOUND")
        item = self._item_attachment_row_to_dict(row._mapping)
        return {
            "bucket": item.get("minioBucket") or settings.minio_buckets["materials"],
            "key": item.get("minioKey") or "",
            "fileName": item.get("fileName") or f"{item['id']}.docx",
            "mimeType": item.get("mimeType") or "application/octet-stream",
            "attachmentType": item.get("attachmentType") or "",
            "sizeBytes": int(item.get("sizeBytes") or 0),
        }

    async def preview_item_attachment(
        self,
        category_id: str,
        item_id: str,
        attachment_id: str,
        *,
        browser_base_url: str = "",
        onlyoffice_base_url: str = "",
    ) -> dict[str, Any]:
        payload = await self.download_item_attachment(category_id, item_id, attachment_id)
        file_name = str(payload.get("fileName") or f"{attachment_id}.docx")
        file_path = f"/api/materials/performance/categories/{category_id}/items/{item_id}/attachments/{attachment_id}"
        return self._preview_payload(
            attachment_id=attachment_id,
            file_name=file_name,
            file_path=file_path,
            minio_key=str(payload.get("key") or ""),
            browser_base_url=browser_base_url,
            onlyoffice_base_url=onlyoffice_base_url,
        )

    def _preview_payload(
        self,
        *,
        attachment_id: str,
        file_name: str,
        file_path: str,
        minio_key: str,
        browser_base_url: str = "",
        onlyoffice_base_url: str = "",
    ) -> dict[str, Any]:
        suffix = Path(file_name).suffix.lower().lstrip(".") or "docx"
        document_type = (
            "cell" if suffix in {"xls", "xlsx", "csv"}
            else "slide" if suffix in {"ppt", "pptx"}
            else "pdf" if suffix == "pdf"
            else "word"
        )
        if suffix not in {"doc", "docx", "xls", "xlsx", "csv", "ppt", "pptx", "pdf"}:
            raise PeripheralError(400, "该附件类型暂不支持在线预览。", "PERFORMANCE_ATTACHMENT_PREVIEW_UNSUPPORTED")
        browser_file_url = f"{browser_base_url.rstrip('/')}{file_path}" if browser_base_url else file_path
        onlyoffice_file_url = (
            f"{onlyoffice_base_url.rstrip('/')}{file_path}"
            if onlyoffice_base_url
            else browser_file_url
        )
        digest = hashlib.sha1("|".join([attachment_id, minio_key, file_name]).encode("utf-8")).hexdigest()[:16]
        return {
            "status": "ready",
            "attachmentId": attachment_id,
            "fileName": file_name,
            "fileType": suffix,
            "documentType": document_type,
            "fileUrl": browser_file_url,
            "onlyoffice": {
                "documentKey": f"performance-{attachment_id}-{digest}",
                "title": file_name,
                "fileUrl": onlyoffice_file_url,
                "browserFileUrl": browser_file_url,
                "documentServerFileUrl": onlyoffice_file_url,
                "fileType": suffix,
                "documentType": document_type,
                "user": {
                    "id": "user-1",
                    "name": "当前用户",
                },
            },
        }

    async def update_category_status(self, category_id: str, status: str) -> dict[str, Any]:
        numeric_id = self._numeric_category_id(category_id)
        selected_status = str(status or "").strip()
        if selected_status not in PERFORMANCE_CATEGORY_STATUSES:
            raise PeripheralError(400, "业绩类别状态无效。", "PERFORMANCE_CATEGORY_STATUS_INVALID")
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            result = await session.execute(
                text(
                    """
                    UPDATE performance_categories
                    SET status = CAST(:status AS VARCHAR),
                        review_status = CASE
                            WHEN CAST(:status AS VARCHAR) = 'enabled' AND review_status = 'disabled' THEN 'draft'
                            ELSE review_status
                        END,
                        updated_at = NOW()
                    WHERE id = :id
                    RETURNING *
                    """
                ),
                {"id": numeric_id, "status": selected_status},
            )
            row = result.first()
            if row is None:
                raise PeripheralError(404, "业绩类别不存在。", "PERFORMANCE_CATEGORY_NOT_FOUND")
            await session.commit()
        return {"message": "业绩类别已启用" if selected_status == "enabled" else "业绩类别已停用", "item": self._category_row_to_dict(row._mapping)}

    async def disable_category(self, category_id: str) -> dict[str, Any]:
        return await self.update_category_status(category_id, "disabled")

    async def delete_category(self, category_id: str, confirm_name: str = "") -> dict[str, Any]:
        numeric_id = self._numeric_category_id(category_id)
        selected_confirm_name = str(confirm_name or "").strip()
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            category_result = await session.execute(
                text(
                    """
                    SELECT id, name
                    FROM performance_categories
                    WHERE id = :id
                    """
                ),
                {"id": numeric_id},
            )
            category_row = category_result.first()
            if category_row is None:
                raise PeripheralError(404, "业绩类别不存在。", "PERFORMANCE_CATEGORY_NOT_FOUND")
            category_name = str(category_row._mapping.get("name") or "").strip()
            if not selected_confirm_name or selected_confirm_name != category_name:
                raise PeripheralError(400, "请输入完整业绩类别名称后再删除。", "PERFORMANCE_CATEGORY_DELETE_CONFIRM_REQUIRED")
            attachment_result = await session.execute(
                text(
                    """
                    SELECT minio_bucket, minio_key
                    FROM performance_attachments
                    WHERE category_id = :id
                    """
                ),
                {"id": numeric_id},
            )
            attachments = [dict(row._mapping) for row in attachment_result]
            item_attachment_result = await session.execute(
                text(
                    """
                    SELECT minio_bucket, minio_key
                    FROM performance_item_attachments
                    WHERE category_id = :id
                    """
                ),
                {"id": numeric_id},
            )
            attachments.extend(dict(row._mapping) for row in item_attachment_result)
            result = await session.execute(
                text(
                    """
                    DELETE FROM performance_categories
                    WHERE id = :id
                    RETURNING id
                    """
                ),
                {"id": numeric_id},
            )
            if result.first() is None:
                raise PeripheralError(404, "业绩类别不存在。", "PERFORMANCE_CATEGORY_NOT_FOUND")
            await session.commit()

        for attachment in attachments:
            bucket = attachment.get("minio_bucket") or settings.minio_buckets["materials"]
            key = attachment.get("minio_key") or ""
            if not key:
                continue
            try:
                minio_client.remove_object(bucket, key)
            except Exception as exc:  # pragma: no cover - object cleanup should not roll back DB delete
                logger.warning("Failed to remove performance attachment object %s/%s: %s", bucket, key, exc)
        return {"message": "业绩类别已删除", "id": f"PERCAT-{numeric_id:04d}"}

    async def update_item(self, category_id: str, item_id: str, data: dict[str, Any]) -> dict[str, Any]:
        numeric_category_id = self._numeric_category_id(category_id)
        numeric_item_id = self._numeric_item_id(item_id)
        payload = data if isinstance(data, dict) else {}
        editable_fields = set(PERFORMANCE_ITEM_EDITABLE_TEXT_FIELDS) | set(PERFORMANCE_ITEM_EDITABLE_YEAR_FIELDS)
        unknown_fields = sorted(str(key) for key in payload if key not in editable_fields)
        if unknown_fields:
            raise PeripheralError(400, f"业绩明细不支持编辑字段：{'、'.join(unknown_fields)}。", "PERFORMANCE_ITEM_FIELDS_INVALID")
        if not any(key in editable_fields for key in payload):
            raise PeripheralError(400, "没有需要更新的业绩明细字段。", "PERFORMANCE_ITEM_UPDATE_EMPTY")
        assignments: list[str] = []
        params: dict[str, Any] = {"category_id": numeric_category_id, "item_id": numeric_item_id}
        text_updates: dict[str, str] = {}
        for field, column in PERFORMANCE_ITEM_EDITABLE_TEXT_FIELDS.items():
            if field not in payload:
                continue
            assignments.append(f"{column} = :{column}")
            value = str(payload.get(field) or "").strip()
            text_updates[field] = value
            params[column] = value
        year_updates: dict[str, int | None] = {}
        for field, (column, label) in PERFORMANCE_ITEM_EDITABLE_YEAR_FIELDS.items():
            if field not in payload:
                continue
            year = _parse_item_year(payload.get(field), field_label=label)
            year_updates[field] = year
            assignments.append(f"{column} = :{column}")
            params[column] = year
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            existing_result = await session.execute(
                text(
                    """
                    SELECT *
                    FROM performance_items
                    WHERE id = :item_id AND category_id = :category_id
                    """
                ),
                {"item_id": numeric_item_id, "category_id": numeric_category_id},
            )
            existing_row = existing_result.first()
            if existing_row is None:
                raise PeripheralError(404, "业绩明细不存在。", "PERFORMANCE_ITEM_NOT_FOUND")
            existing = dict(existing_row._mapping)
            text_changes = {
                field: value
                for field, value in text_updates.items()
                if value != str(existing.get(PERFORMANCE_ITEM_EDITABLE_TEXT_FIELDS[field]) or "").strip()
            }
            year_changes = {
                field: year
                for field, year in year_updates.items()
                if year != existing.get(PERFORMANCE_ITEM_EDITABLE_YEAR_FIELDS[field][0])
            }
            row_values = _sync_performance_item_row_values(
                existing.get("row_values"),
                existing=existing,
                text_updates=text_updates,
                changed_text_fields=set(text_changes),
                year_updates=year_changes,
            )
            original_row_values = dict(existing.get("row_values") or {})
            if row_values != original_row_values:
                assignments.append("row_values = CAST(:row_values AS JSONB)")
                params["row_values"] = _json(row_values)
            if "turbineModel" in text_changes:
                assignments.append("turbine_models = CAST(:turbine_models AS JSONB)")
                params["turbine_models"] = _json(_split_turbine_models(params["turbine_model"]))
            previous_parsed_time_facts = _time_facts(original_row_values)
            parsed_time_facts = _time_facts(row_values)
            raw_time_keys = ("contractTimeRaw", "deliveryTimeRaw", "operationTimeRaw", "deliveryOrOperationTimeRaw")
            time_facts_changed = bool(year_changes) or any(
                previous_parsed_time_facts.get(key) != parsed_time_facts.get(key) for key in raw_time_keys
            )
            time_facts = dict(existing.get("time_facts") or {})
            if time_facts_changed:
                for key in raw_time_keys:
                    time_facts[key] = parsed_time_facts.get(key) or ""
                effective_years: list[int | None] = []
                for field, (column, _label) in PERFORMANCE_ITEM_EDITABLE_YEAR_FIELDS.items():
                    year = year_updates[field] if field in year_updates else existing.get(column)
                    time_facts[field] = year
                    effective_years.append(year)
                time_facts["years"] = _unique_ints(effective_years)
                assignments.append("time_facts = CAST(:time_facts AS JSONB)")
                params["time_facts"] = _json(time_facts)
            result = await session.execute(
                text(
                    f"""
                    UPDATE performance_items
                    SET {", ".join(assignments)}, updated_at = NOW()
                    WHERE id = :item_id AND category_id = :category_id
                    RETURNING *
                    """
                ),
                params,
            )
            row = result.first()
            if row is None:
                raise PeripheralError(404, "业绩明细不存在。", "PERFORMANCE_ITEM_NOT_FOUND")
            await session.execute(
                text("UPDATE performance_categories SET updated_at = NOW() WHERE id = :category_id"),
                {"category_id": numeric_category_id},
            )
            await session.commit()
        return {"message": "业绩明细已更新", "item": self._item_row_to_dict(row._mapping)}

    async def create_item(self, category_id: str, data: dict[str, Any]) -> dict[str, Any]:
        numeric_category_id = self._numeric_category_id(category_id)
        payload = data if isinstance(data, dict) else {}
        editable_fields = set(PERFORMANCE_ITEM_EDITABLE_TEXT_FIELDS) | set(PERFORMANCE_ITEM_EDITABLE_YEAR_FIELDS)
        unknown_fields = sorted(str(key) for key in payload if key not in editable_fields)
        if unknown_fields:
            raise PeripheralError(400, f"业绩明细不支持编辑字段：{'、'.join(unknown_fields)}。", "PERFORMANCE_ITEM_FIELDS_INVALID")
        text_values: dict[str, str] = {}
        for field in PERFORMANCE_ITEM_EDITABLE_TEXT_FIELDS:
            if field not in payload:
                continue
            text_values[field] = str(payload.get(field) or "").strip()
        year_values: dict[str, int | None] = {}
        for field, (_column, label) in PERFORMANCE_ITEM_EDITABLE_YEAR_FIELDS.items():
            if field not in payload:
                continue
            year_values[field] = _parse_item_year(payload.get(field), field_label=label)
        if not any(text_values.values()) and not any(year is not None for year in year_values.values()):
            raise PeripheralError(400, "业绩明细内容不能为空。", "PERFORMANCE_ITEM_CREATE_EMPTY")
        row_values = _sync_performance_item_row_values(
            None,
            existing={},
            text_updates=text_values,
            changed_text_fields=set(text_values),
            year_updates=year_values,
        )
        parsed_time_facts = _time_facts(row_values)
        time_facts: dict[str, Any] = {}
        for key in ("contractTimeRaw", "deliveryTimeRaw", "operationTimeRaw", "deliveryOrOperationTimeRaw"):
            time_facts[key] = parsed_time_facts.get(key) or ""
        effective_years: list[int | None] = []
        for field, (_column, _label) in PERFORMANCE_ITEM_EDITABLE_YEAR_FIELDS.items():
            year = year_values.get(field)
            time_facts[field] = year
            effective_years.append(year)
        time_facts["years"] = _unique_ints(effective_years)
        turbine_model = text_values.get("turbineModel", "")
        params: dict[str, Any] = {
            "category_id": numeric_category_id,
            "project_name": text_values.get("projectName", ""),
            "customer_name": text_values.get("customerName", ""),
            "partner_name": text_values.get("partnerName", ""),
            "turbine_model": turbine_model,
            "turbine_models": _json(_split_turbine_models(turbine_model)),
            "contract_quantity": text_values.get("contractQuantity", ""),
            "trial_operation_quantity": text_values.get("trialOperationQuantity", ""),
            "commissioned_capacity_mw": text_values.get("commissionedCapacityMw", ""),
            "delivery_or_operation_time": text_values.get("deliveryOrOperationTime", ""),
            "contract_year": year_values.get("contractYear"),
            "delivery_year": year_values.get("deliveryYear"),
            "operation_year": year_values.get("operationYear"),
            "time_facts": _json(time_facts),
            "contact_info": text_values.get("contactInfo", ""),
            "row_values": _json(row_values),
        }
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            category_result = await session.execute(
                text(
                    """
                    SELECT id
                    FROM performance_categories
                    WHERE id = :category_id
                    """
                ),
                {"category_id": numeric_category_id},
            )
            if category_result.first() is None:
                raise PeripheralError(404, "业绩类别不存在。", "PERFORMANCE_CATEGORY_NOT_FOUND")
            row_index_result = await session.execute(
                text(
                    """
                    SELECT COALESCE(MAX(row_index), 0) + 1
                    FROM performance_items
                    WHERE category_id = :category_id
                    """
                ),
                {"category_id": numeric_category_id},
            )
            params["row_index"] = int(row_index_result.scalar_one() or 1)
            result = await session.execute(
                text(
                    """
                    INSERT INTO performance_items (
                        category_id, row_index, project_name, customer_name, partner_name, turbine_model,
                        turbine_models,
                        contract_quantity, trial_operation_quantity, commissioned_capacity_mw,
                        delivery_or_operation_time, contract_year, delivery_year, operation_year,
                        time_facts, contact_info, row_values
                    )
                    VALUES (
                        :category_id, :row_index, :project_name, :customer_name, :partner_name, :turbine_model,
                        CAST(:turbine_models AS JSONB),
                        :contract_quantity, :trial_operation_quantity, :commissioned_capacity_mw,
                        :delivery_or_operation_time, :contract_year, :delivery_year, :operation_year,
                        CAST(:time_facts AS JSONB), :contact_info, CAST(:row_values AS JSONB)
                    )
                    RETURNING *
                    """
                ),
                params,
            )
            row = result.first()
            if row is None:
                raise PeripheralError(500, "业绩明细创建失败。", "PERFORMANCE_ITEM_CREATE_FAILED")
            await session.execute(
                text("UPDATE performance_categories SET updated_at = NOW() WHERE id = :category_id"),
                {"category_id": numeric_category_id},
            )
            await session.commit()
        return {"message": "业绩明细已新增", "item": self._item_row_to_dict(row._mapping)}

    async def delete_item(self, category_id: str, item_id: str) -> dict[str, Any]:
        numeric_category_id = self._numeric_category_id(category_id)
        numeric_item_id = self._numeric_item_id(item_id)
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            attachment_result = await session.execute(
                text(
                    """
                    DELETE FROM performance_item_attachments
                    WHERE item_id = :item_id AND category_id = :category_id
                    RETURNING minio_bucket, minio_key
                    """
                ),
                {"item_id": numeric_item_id, "category_id": numeric_category_id},
            )
            attachments = [dict(row._mapping) for row in attachment_result]
            result = await session.execute(
                text(
                    """
                    DELETE FROM performance_items
                    WHERE id = :item_id AND category_id = :category_id
                    RETURNING id
                    """
                ),
                {"item_id": numeric_item_id, "category_id": numeric_category_id},
            )
            if result.first() is None:
                raise PeripheralError(404, "业绩明细不存在。", "PERFORMANCE_ITEM_NOT_FOUND")
            await session.execute(
                text("UPDATE performance_categories SET updated_at = NOW() WHERE id = :category_id"),
                {"category_id": numeric_category_id},
            )
            await session.commit()

        for attachment in attachments:
            bucket = attachment.get("minio_bucket") or settings.minio_buckets["materials"]
            key = attachment.get("minio_key") or ""
            if not key:
                continue
            try:
                minio_client.remove_object(bucket, key)
            except Exception as exc:  # pragma: no cover - object cleanup should not roll back DB delete
                logger.warning("Failed to remove performance item attachment object %s/%s: %s", bucket, key, exc)
        return {"message": "业绩明细已删除", "id": f"PERITEM-{numeric_item_id:04d}"}

    def _category_filters(
        self,
        *,
        keyword: str,
        scene: str,
        power_rating: str,
        turbine_model: str,
        time_keyword: str,
        contract_year: str,
        delivery_year: str,
        operation_year: str,
        tag: str,
        status: str,
    ) -> tuple[list[str], dict[str, Any]]:
        filters: list[str] = []
        params: dict[str, Any] = {}
        selected_status = str(status or "").strip()
        if selected_status in PERFORMANCE_CATEGORY_STATUSES:
            filters.append("COALESCE(c.status, CASE WHEN c.review_status = 'disabled' THEN 'disabled' ELSE 'enabled' END) = :status")
            params["status"] = selected_status
        kw = str(keyword or "").strip()
        if kw:
            filters.append(
                "("
                "c.name ILIKE :keyword OR c.scene ILIKE :keyword OR c.power_rating ILIKE :keyword OR "
                "c.summary ILIKE :keyword OR EXISTS ("
                "SELECT 1 FROM performance_items i WHERE i.category_id = c.id AND "
                "(i.project_name ILIKE :keyword OR i.customer_name ILIKE :keyword OR "
                "i.turbine_model ILIKE :keyword OR i.row_values::text ILIKE :keyword)"
                ")"
                ")"
            )
            params["keyword"] = f"%{kw}%"
        selected_scene = str(scene or "").strip()
        if selected_scene:
            filters.append("c.scene ILIKE :scene")
            params["scene"] = f"%{selected_scene}%"
        selected_power = str(power_rating or "").strip()
        if selected_power:
            filters.append("c.power_rating ILIKE :power_rating")
            params["power_rating"] = f"%{selected_power}%"
        selected_model = str(turbine_model or "").strip()
        if selected_model:
            filters.append(
                """
                EXISTS (
                    SELECT 1
                    FROM performance_items i
                    WHERE i.category_id = c.id
                      AND (
                        i.turbine_model ILIKE :turbine_model OR
                        i.turbine_models::text ILIKE :turbine_model OR
                        i.row_values::text ILIKE :turbine_model
                      )
                )
                """
            )
            params["turbine_model"] = f"%{selected_model}%"
        selected_time = str(time_keyword or "").strip()
        if selected_time:
            filters.append(
                """
                EXISTS (
                    SELECT 1
                    FROM performance_items i
                    WHERE i.category_id = c.id
                      AND (
                        i.delivery_or_operation_time ILIKE :time_keyword OR
                        i.time_facts::text ILIKE :time_keyword OR
                        i.row_values::text ILIKE :time_keyword
                      )
                )
                """
            )
            params["time_keyword"] = f"%{selected_time}%"
        contract_year_value = _parse_year_filter(contract_year)
        if contract_year_value is not None:
            filters.append(
                """
                EXISTS (
                    SELECT 1
                    FROM performance_items i
                    WHERE i.category_id = c.id AND i.contract_year = :contract_year
                )
                """
            )
            params["contract_year"] = contract_year_value
        delivery_year_value = _parse_year_filter(delivery_year)
        if delivery_year_value is not None:
            filters.append(
                """
                EXISTS (
                    SELECT 1
                    FROM performance_items i
                    WHERE i.category_id = c.id AND i.delivery_year = :delivery_year
                )
                """
            )
            params["delivery_year"] = delivery_year_value
        operation_year_value = _parse_year_filter(operation_year)
        if operation_year_value is not None:
            filters.append(
                """
                EXISTS (
                    SELECT 1
                    FROM performance_items i
                    WHERE i.category_id = c.id AND i.operation_year = :operation_year
                )
                """
            )
            params["operation_year"] = operation_year_value
        selected_tag = str(tag or "").strip()
        if selected_tag:
            filters.append("c.tags @> CAST(:tag_json AS JSONB)")
            params["tag_json"] = _json([selected_tag])
        return filters, params

    async def _backfill_derived_item_fields(self, session: Any, *, category_id: int | None = None) -> None:
        filters = [
            "("
            "COALESCE(jsonb_array_length(COALESCE(turbine_models, '[]'::jsonb)), 0) = 0 OR "
            "COALESCE(time_facts, '{}'::jsonb) = '{}'::jsonb"
            ")"
        ]
        params: dict[str, Any] = {}
        if category_id is not None:
            filters.append("category_id = :category_id")
            params["category_id"] = category_id
        rows = await session.execute(
            text(
                f"""
                SELECT id, row_values, turbine_model, delivery_or_operation_time
                FROM performance_items
                WHERE {' AND '.join(filters)}
                LIMIT 2000
                """
            ),
            params,
        )
        updates: list[dict[str, Any]] = []
        for row in rows:
            row_dict = dict(row._mapping)
            row_values = dict(row_dict.get("row_values") or {})
            if not row_values:
                turbine_model = str(row_dict.get("turbine_model") or "").strip()
                delivery_or_operation_time = str(row_dict.get("delivery_or_operation_time") or "").strip()
                if turbine_model:
                    row_values["型号"] = turbine_model
                if delivery_or_operation_time:
                    row_values["交货期/投运时间"] = delivery_or_operation_time
            core = _core_values(row_values)
            updates.append(
                {
                    "id": row_dict["id"],
                    "turbine_models": _json(core.get("turbineModels") or []),
                    "contract_year": core.get("contractYear"),
                    "delivery_year": core.get("deliveryYear"),
                    "operation_year": core.get("operationYear"),
                    "time_facts": _json(core.get("timeFacts") or {}),
                }
            )
        if not updates:
            return
        await session.execute(
            text(
                """
                UPDATE performance_items
                SET turbine_models = CAST(:turbine_models AS JSONB),
                    contract_year = :contract_year,
                    delivery_year = :delivery_year,
                    operation_year = :operation_year,
                    time_facts = CAST(:time_facts AS JSONB),
                    updated_at = NOW()
                WHERE id = :id
                """
            ),
            updates,
        )
        await session.commit()

    async def _ensure_contract_item_attachments(self, session: Any, *, category_id: int) -> None:
        source_rows = await session.execute(
            text(
                """
                SELECT *
                FROM performance_attachments
                WHERE category_id = :category_id
                  AND attachment_type = :attachment_type
                  AND LOWER(file_name) LIKE '%.docx'
                ORDER BY id ASC
                LIMIT 20
                """
            ),
            {"category_id": category_id, "attachment_type": CONTRACT_ATTACHMENT_TYPE},
        )
        for row in source_rows:
            source = dict(row._mapping)
            existing_result = await session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM performance_item_attachments
                    WHERE source_attachment_id = :source_attachment_id
                      AND COALESCE(format_version, 1) >= :format_version
                    """
                ),
                {
                    "source_attachment_id": int(source.get("id") or 0),
                    "format_version": ITEM_CONTRACT_FORMAT_VERSION,
                },
            )
            if int(existing_result.scalar_one() or 0) > 0:
                continue
            try:
                content = minio_client.get_object(
                    source.get("minio_bucket") or settings.minio_buckets["materials"],
                    source.get("minio_key") or "",
                )
                await self._replace_contract_item_attachments_for_source(
                    session,
                    category_id=category_id,
                    source_attachment_id=int(source["id"]),
                    content=content,
                    source_file_name=str(source.get("file_name") or "合同附件.docx"),
                )
                await session.commit()
            except Exception as exc:  # pragma: no cover - lazy split should not break detail loading
                logger.warning("Failed to lazily split performance contract attachment %s: %s", source.get("id"), exc)
                await session.rollback()
                await ensure_material_runtime_tables(session)

    async def _replace_contract_item_attachments_for_source(
        self,
        session: Any,
        *,
        category_id: int,
        source_attachment_id: int,
        content: bytes,
        source_file_name: str,
    ) -> list[tuple[str, str]]:
        old_rows = await session.execute(
            text(
                """
                DELETE FROM performance_item_attachments
                WHERE source_attachment_id = :source_attachment_id
                RETURNING minio_bucket, minio_key
                """
            ),
            {"source_attachment_id": source_attachment_id},
        )
        for row in old_rows:
            bucket = row._mapping.get("minio_bucket") or settings.minio_buckets["materials"]
            key = row._mapping.get("minio_key") or ""
            if not key:
                continue
            try:
                minio_client.remove_object(bucket, key)
            except Exception as exc:  # pragma: no cover - cleanup should not block a replacement split
                logger.warning("Failed to remove old split performance contract object %s/%s: %s", bucket, key, exc)

        chunks = split_performance_contract_docx(content, file_name=source_file_name)
        if not chunks:
            return []
        item_rows = await session.execute(
            text(
                """
                SELECT id, row_index, project_name, customer_name, turbine_model, turbine_models, row_values
                FROM performance_items
                WHERE category_id = :category_id
                ORDER BY row_index ASC, id ASC
                """
            ),
            {"category_id": category_id},
        )
        items = [self._item_row_to_dict(row._mapping) for row in item_rows]
        matches = match_contract_chunks_to_items(chunks, items)
        uploaded_objects: list[tuple[str, str]] = []
        inserts: list[dict[str, Any]] = []
        bucket = settings.minio_buckets["materials"]
        for match in matches:
            item = match.get("item") or {}
            chunk = match.get("chunk") or {}
            item_numeric_id = self._numeric_item_id(str(item.get("id") or ""))
            if not item_numeric_id:
                continue
            chunk_content = chunk.get("content")
            if not isinstance(chunk_content, bytes):
                chunk_content = render_contract_item_docx(
                    chunk,
                    output_title=str(item.get("projectName") or chunk.get("title") or ""),
                )
            file_name = _contract_item_file_name(
                item.get("rowIndex") or 0,
                item.get("projectName") or chunk.get("title") or Path(source_file_name).stem,
                chunk.get("index") or 0,
            )
            object_key = (
                f"performance-categories/PERCAT-{category_id:04d}/"
                f"item-contracts/PERITEM-{item_numeric_id:04d}/"
                f"SRC-{source_attachment_id:04d}-{safe_filename(file_name, "performance.docx")}"
            )
            minio_client.put_object(bucket, object_key, chunk_content, content_type=DOCX_MIME_TYPE)
            uploaded_objects.append((bucket, object_key))
            inserts.append(
                {
                    "category_id": category_id,
                    "item_id": item_numeric_id,
                    "source_attachment_id": source_attachment_id,
                    "attachment_type": ITEM_CONTRACT_ATTACHMENT_TYPE,
                    "file_name": file_name,
                    "minio_key": object_key,
                    "minio_bucket": bucket,
                    "mime_type": DOCX_MIME_TYPE,
                    "size_bytes": len(chunk_content),
                    "format_version": ITEM_CONTRACT_FORMAT_VERSION,
                    "match_confidence": int(match.get("confidence") or 0),
                    "match_method": str(match.get("method") or ""),
                    "source_title": str(chunk.get("title") or ""),
                    "source_block_start": chunk.get("blockStart"),
                    "source_block_end": chunk.get("blockEnd"),
                }
            )
        if inserts:
            await session.execute(
                text(
                    """
                    INSERT INTO performance_item_attachments (
                        category_id, item_id, source_attachment_id, attachment_type, file_name,
                        minio_key, minio_bucket, mime_type, size_bytes, format_version, match_confidence,
                        match_method, source_title, source_block_start, source_block_end
                    )
                    VALUES (
                        :category_id, :item_id, :source_attachment_id, :attachment_type, :file_name,
                        :minio_key, :minio_bucket, :mime_type, :size_bytes, :format_version, :match_confidence,
                        :match_method, :source_title, :source_block_start, :source_block_end
                    )
                    """
                ),
                inserts,
            )
        return uploaded_objects

    def _category_row_to_dict(self, row: Any) -> dict[str, Any]:
        row_dict = dict(row)
        numeric_id = int(row_dict.get("id") or 0)
        return {
            "id": f"PERCAT-{numeric_id:04d}",
            "name": row_dict.get("name") or "",
            "scene": row_dict.get("scene") or "",
            "powerRating": row_dict.get("power_rating") or "",
            "summary": row_dict.get("summary") or "",
            "fieldSchema": list(row_dict.get("field_schema") or []),
            "turbineModels": list(row_dict.get("turbine_models") or []),
            "contractYears": list(row_dict.get("contract_years") or []),
            "deliveryYears": list(row_dict.get("delivery_years") or []),
            "operationYears": list(row_dict.get("operation_years") or []),
            "tags": list(row_dict.get("tags") or []),
            "scope": row_dict.get("scope") or "standard",
            "status": row_dict.get("status") or ("disabled" if row_dict.get("review_status") == "disabled" else "enabled"),
            "reviewStatus": row_dict.get("review_status") or "draft",
            "itemCount": int(row_dict.get("item_count") or 0),
            "attachmentCount": int(row_dict.get("attachment_count") or 0),
            "contractAttachmentCount": int(row_dict.get("contract_attachment_count") or 0),
            "itemContractAttachmentCount": int(row_dict.get("item_contract_attachment_count") or 0),
            "summaryFileName": row_dict.get("summary_file_name") or "",
            "contractFileName": row_dict.get("contract_file_name") or "",
            "createdAt": row_dict.get("created_at").isoformat() if row_dict.get("created_at") else "",
            "updatedAt": row_dict.get("updated_at").isoformat() if row_dict.get("updated_at") else "",
        }

    def _item_row_to_dict(self, row: Any) -> dict[str, Any]:
        row_dict = dict(row)
        numeric_id = int(row_dict.get("id") or 0)
        return {
            "id": f"PERITEM-{numeric_id:04d}",
            "categoryId": f"PERCAT-{int(row_dict.get('category_id') or 0):04d}",
            "rowIndex": int(row_dict.get("row_index") or 0),
            "projectName": row_dict.get("project_name") or "",
            "customerName": row_dict.get("customer_name") or "",
            "partnerName": row_dict.get("partner_name") or "",
            "turbineModel": row_dict.get("turbine_model") or "",
            "turbineModels": list(row_dict.get("turbine_models") or []),
            "contractQuantity": row_dict.get("contract_quantity") or "",
            "trialOperationQuantity": row_dict.get("trial_operation_quantity") or "",
            "commissionedCapacityMw": row_dict.get("commissioned_capacity_mw") or "",
            "deliveryOrOperationTime": row_dict.get("delivery_or_operation_time") or "",
            "contractYear": row_dict.get("contract_year"),
            "deliveryYear": row_dict.get("delivery_year"),
            "operationYear": row_dict.get("operation_year"),
            "timeFacts": dict(row_dict.get("time_facts") or {}),
            "contactInfo": row_dict.get("contact_info") or "",
            "values": dict(row_dict.get("row_values") or {}),
            "createdAt": row_dict.get("created_at").isoformat() if row_dict.get("created_at") else "",
            "updatedAt": row_dict.get("updated_at").isoformat() if row_dict.get("updated_at") else "",
        }

    def _attachment_row_to_dict(self, row: Any) -> dict[str, Any]:
        row_dict = dict(row)
        numeric_id = int(row_dict.get("id") or 0)
        return {
            "id": f"PERATT-{numeric_id:04d}",
            "categoryId": f"PERCAT-{int(row_dict.get('category_id') or 0):04d}",
            "attachmentType": row_dict.get("attachment_type") or "",
            "fileName": row_dict.get("file_name") or "",
            "minioKey": row_dict.get("minio_key") or "",
            "minioBucket": row_dict.get("minio_bucket") or settings.minio_buckets["materials"],
            "mimeType": row_dict.get("mime_type") or "",
            "sizeBytes": int(row_dict.get("size_bytes") or 0),
            "createdAt": row_dict.get("created_at").isoformat() if row_dict.get("created_at") else "",
        }

    def _item_attachment_row_to_dict(self, row: Any) -> dict[str, Any]:
        row_dict = dict(row)
        numeric_id = int(row_dict.get("id") or 0)
        return {
            "id": f"PERITEMATT-{numeric_id:04d}",
            "categoryId": f"PERCAT-{int(row_dict.get('category_id') or 0):04d}",
            "itemId": f"PERITEM-{int(row_dict.get('item_id') or 0):04d}",
            "sourceAttachmentId": f"PERATT-{int(row_dict.get('source_attachment_id') or 0):04d}" if row_dict.get("source_attachment_id") else "",
            "attachmentType": row_dict.get("attachment_type") or "",
            "fileName": row_dict.get("file_name") or "",
            "minioKey": row_dict.get("minio_key") or "",
            "minioBucket": row_dict.get("minio_bucket") or settings.minio_buckets["materials"],
            "mimeType": row_dict.get("mime_type") or "",
            "sizeBytes": int(row_dict.get("size_bytes") or 0),
            "matchConfidence": int(row_dict.get("match_confidence") or 0),
            "matchMethod": row_dict.get("match_method") or "",
            "sourceTitle": row_dict.get("source_title") or "",
            "sourceBlockStart": row_dict.get("source_block_start"),
            "sourceBlockEnd": row_dict.get("source_block_end"),
            "createdAt": row_dict.get("created_at").isoformat() if row_dict.get("created_at") else "",
        }

    def _numeric_category_id(self, category_id: str) -> int:
        try:
            return int(str(category_id or "").replace("PERCAT-", ""))
        except ValueError as exc:
            raise PeripheralError(400, "业绩类别 ID 无效。", "PERFORMANCE_CATEGORY_ID_INVALID") from exc

    def _numeric_item_id(self, item_id: str) -> int:
        try:
            return int(str(item_id or "").replace("PERITEM-", ""))
        except ValueError as exc:
            raise PeripheralError(400, "业绩明细 ID 无效。", "PERFORMANCE_ITEM_ID_INVALID") from exc

    def _numeric_attachment_id(self, attachment_id: str) -> int:
        try:
            return int(str(attachment_id or "").replace("PERATT-", ""))
        except ValueError as exc:
            raise PeripheralError(400, "业绩附件 ID 无效。", "PERFORMANCE_ATTACHMENT_ID_INVALID") from exc

    def _numeric_item_attachment_id(self, attachment_id: str) -> int:
        try:
            return int(str(attachment_id or "").replace("PERITEMATT-", ""))
        except ValueError as exc:
            raise PeripheralError(400, "项目合同附件 ID 无效。", "PERFORMANCE_ITEM_ATTACHMENT_ID_INVALID") from exc


async def _read_upload(upload: Any) -> tuple[bytes, str, str]:
    file_name = safe_filename(str(getattr(upload, "filename", "") or "performance.docx"), "performance.docx")
    if not file_name.lower().endswith((".doc", ".docx")):
        raise PeripheralError(400, "业绩包仅支持上传 Word 文件。", "PERFORMANCE_WORD_REQUIRED")
    content = await upload.read()
    if len(content) > settings.max_upload_file_size_bytes:
        limit_mb = settings.max_upload_file_size_bytes // 1024 // 1024
        raise PeripheralError(413, f"文件超过 {limit_mb}MB 上限。", "PERFORMANCE_FILE_TOO_LARGE")
    mime_type = str(getattr(upload, "content_type", "") or "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    return content, file_name, mime_type


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _category_order_sql(sort_by: str, sort_order: str) -> str:
    direction = "ASC" if str(sort_order or "").lower() == "asc" else "DESC"
    order_map = {
        "name": "c.name",
        "scene": "c.scene",
        "powerRating": "c.power_rating",
        "itemCount": "item_count",
        "fieldCount": "jsonb_array_length(COALESCE(c.field_schema, '[]'::jsonb))",
        "attachmentCount": "attachment_count",
        "status": "COALESCE(c.status, CASE WHEN c.review_status = 'disabled' THEN 'disabled' ELSE 'enabled' END)",
        "reviewStatus": "c.review_status",
        "updatedAt": "c.updated_at",
        "createdAt": "c.created_at",
    }
    expression = order_map.get(str(sort_by or "").strip(), "c.updated_at")
    return f"ORDER BY {expression} {direction} NULLS LAST, c.id DESC"


def _item_order_sql(sort_by: str, sort_order: str) -> str:
    direction = "ASC" if str(sort_order or "").lower() == "asc" else "DESC"
    order_map = {
        "projectName": "i.project_name",
        "customerName": "i.customer_name",
        "turbineModel": "i.turbine_model",
        "contractYear": "i.contract_year",
        "deliveryYear": "i.delivery_year",
        "operationYear": "i.operation_year",
        "categoryName": "c.name",
        "rowIndex": "i.row_index",
        "updatedAt": "i.updated_at",
        "createdAt": "i.created_at",
    }
    expression = order_map.get(str(sort_by or "").strip(), "i.updated_at")
    return f"ORDER BY {expression} {direction} NULLS LAST, i.id DESC"


performance_package_service = PerformancePackageService()
