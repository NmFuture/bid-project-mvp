from __future__ import annotations

import json
import logging
import re
from io import BytesIO
from pathlib import Path
from typing import Any

from docx import Document
from sqlalchemy import text

from app.core.config import settings
from app.models import async_session
from app.services.material_runtime_tables import ensure_material_runtime_tables
from app.services.material_tags import normalize_material_tags
from app.services.minio_client import minio_client
from app.services.peripheral import PeripheralError


PERFORMANCE_CATEGORY_SCOPES = {"standard", "customer", "project"}
PERFORMANCE_CATEGORY_REVIEW_STATUSES = {"draft", "reviewed", "disabled"}
PERFORMANCE_CATEGORY_STATUSES = {"enabled", "disabled"}
SUMMARY_ATTACHMENT_TYPE = "summary_table"
CONTRACT_ATTACHMENT_TYPE = "contract_bundle"
logger = logging.getLogger(__name__)


class PerformancePackageService:
    async def list_categories(
        self,
        *,
        keyword: str = "",
        scene: str = "",
        power_rating: str = "",
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
            tag=tag,
            status=status,
        )
        where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
        order_sql = _category_order_sql(sort_by, sort_order)
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
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
                        (SELECT COUNT(*) FROM performance_attachments a WHERE a.category_id = c.id) AS attachment_count,
                        (
                            SELECT COUNT(*)
                            FROM performance_attachments a
                            WHERE a.category_id = c.id AND a.attachment_type = :contract_attachment_type
                        ) AS contract_attachment_count,
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
                },
            )
        return {
            "items": [self._category_row_to_dict(row._mapping) for row in rows],
            "total": total,
            "page": current_page,
            "pageSize": current_page_size,
        }

    async def get_category(self, category_id: str) -> dict[str, Any]:
        numeric_id = self._numeric_category_id(category_id)
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            category_result = await session.execute(
                text(
                    """
                    SELECT
                        c.*,
                        (SELECT COUNT(*) FROM performance_items i WHERE i.category_id = c.id) AS item_count,
                        (SELECT COUNT(*) FROM performance_attachments a WHERE a.category_id = c.id) AS attachment_count,
                        (
                            SELECT COUNT(*)
                            FROM performance_attachments a
                            WHERE a.category_id = c.id AND a.attachment_type = :contract_attachment_type
                        ) AS contract_attachment_count,
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
        return {
            "item": self._category_row_to_dict(category_row._mapping),
            "rows": [self._item_row_to_dict(row._mapping) for row in item_rows],
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
        category_name: str = "",
        scene: str = "",
        power_rating: str = "",
        tags: Any = None,
        scope: str = "standard",
        review_status: str = "draft",
    ) -> dict[str, Any]:
        content, file_name, mime_type = await _read_upload(upload)
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
                            category_id, row_index, project_name, customer_name, turbine_model,
                            contract_quantity, trial_operation_quantity, commissioned_capacity_mw,
                            delivery_or_operation_time, contact_info, row_values
                        )
                        VALUES (
                            :category_id, :row_index, :project_name, :customer_name, :turbine_model,
                            :contract_quantity, :trial_operation_quantity, :commissioned_capacity_mw,
                            :delivery_or_operation_time, :contact_info, CAST(:row_values AS JSONB)
                        )
                        """
                    ),
                    [
                        {
                            "category_id": numeric_id,
                            "row_index": int(row.get("rowIndex") or index + 1),
                            "project_name": row.get("projectName") or "",
                            "customer_name": row.get("customerName") or "",
                            "turbine_model": row.get("turbineModel") or "",
                            "contract_quantity": row.get("contractQuantity") or "",
                            "trial_operation_quantity": row.get("trialOperationQuantity") or "",
                            "commissioned_capacity_mw": row.get("commissionedCapacityMw") or "",
                            "delivery_or_operation_time": row.get("deliveryOrOperationTime") or "",
                            "contact_info": row.get("contactInfo") or "",
                            "row_values": _json(row.get("values") or {}),
                        }
                        for index, row in enumerate(parsed.get("rows") or [])
                    ],
                )

            object_key = f"performance-categories/PERCAT-{numeric_id:04d}/summary/{_safe_file_name(file_name)}"
            try:
                minio_client.put_object(
                    settings.minio_buckets["materials"],
                    object_key,
                    content,
                    content_type=mime_type,
                )
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
                        "minio_bucket": settings.minio_buckets["materials"],
                        "mime_type": mime_type,
                        "size_bytes": len(content),
                    },
                )
                await session.commit()
            except Exception:
                minio_client.remove_object(settings.minio_buckets["materials"], object_key)
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
        object_key = f"performance-categories/PERCAT-{numeric_id:04d}/{normalized_type}/{_safe_file_name(file_name)}"
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            category_result = await session.execute(
                text("SELECT id FROM performance_categories WHERE id = :id"),
                {"id": numeric_id},
            )
            if category_result.first() is None:
                raise PeripheralError(404, "业绩类别不存在。", "PERFORMANCE_CATEGORY_NOT_FOUND")
            try:
                minio_client.put_object(
                    settings.minio_buckets["materials"],
                    object_key,
                    content,
                    content_type=mime_type,
                )
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
                        "attachment_type": normalized_type,
                        "file_name": file_name,
                        "minio_key": object_key,
                        "minio_bucket": settings.minio_buckets["materials"],
                        "mime_type": mime_type,
                        "size_bytes": len(content),
                    },
                )
                await session.execute(
                    text("UPDATE performance_categories SET updated_at = NOW() WHERE id = :id"),
                    {"id": numeric_id},
                )
                await session.commit()
            except Exception:
                minio_client.remove_object(settings.minio_buckets["materials"], object_key)
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

    def _category_filters(
        self,
        *,
        keyword: str,
        scene: str,
        power_rating: str,
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
        selected_tag = str(tag or "").strip()
        if selected_tag:
            filters.append("c.tags @> CAST(:tag_json AS JSONB)")
            params["tag_json"] = _json([selected_tag])
        return filters, params

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
            "tags": list(row_dict.get("tags") or []),
            "scope": row_dict.get("scope") or "standard",
            "status": row_dict.get("status") or ("disabled" if row_dict.get("review_status") == "disabled" else "enabled"),
            "reviewStatus": row_dict.get("review_status") or "draft",
            "itemCount": int(row_dict.get("item_count") or 0),
            "attachmentCount": int(row_dict.get("attachment_count") or 0),
            "contractAttachmentCount": int(row_dict.get("contract_attachment_count") or 0),
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
            "turbineModel": row_dict.get("turbine_model") or "",
            "contractQuantity": row_dict.get("contract_quantity") or "",
            "trialOperationQuantity": row_dict.get("trial_operation_quantity") or "",
            "commissionedCapacityMw": row_dict.get("commissioned_capacity_mw") or "",
            "deliveryOrOperationTime": row_dict.get("delivery_or_operation_time") or "",
            "contactInfo": row_dict.get("contact_info") or "",
            "values": dict(row_dict.get("row_values") or {}),
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

    def _numeric_category_id(self, category_id: str) -> int:
        try:
            return int(str(category_id or "").replace("PERCAT-", ""))
        except ValueError as exc:
            raise PeripheralError(400, "业绩类别 ID 无效。", "PERFORMANCE_CATEGORY_ID_INVALID") from exc

    def _numeric_attachment_id(self, attachment_id: str) -> int:
        try:
            return int(str(attachment_id or "").replace("PERATT-", ""))
        except ValueError as exc:
            raise PeripheralError(400, "业绩附件 ID 无效。", "PERFORMANCE_ATTACHMENT_ID_INVALID") from exc


def parse_performance_summary_docx(content: bytes, *, file_name: str = "performance.docx") -> dict[str, Any]:
    if not file_name.lower().endswith(".docx"):
        raise PeripheralError(400, "业绩汇总表解析仅支持 .docx 文件。", "PERFORMANCE_SUMMARY_DOCX_REQUIRED")
    try:
        doc = Document(BytesIO(content))
    except Exception as exc:
        raise PeripheralError(400, "业绩汇总表无法读取，请确认文件格式。", "PERFORMANCE_SUMMARY_DOCX_INVALID") from exc

    paragraphs = [_clean_text(paragraph.text) for paragraph in doc.paragraphs]
    category_name = _infer_category_name(paragraphs, file_name=file_name)
    summary = _infer_summary(paragraphs, category_name=category_name)
    scene = _infer_scene(category_name)
    power_rating = _infer_power_rating(category_name)

    selected_table = _select_summary_table(doc.tables)
    if selected_table is None:
        raise PeripheralError(400, "未在文件中识别到业绩汇总表。", "PERFORMANCE_SUMMARY_TABLE_NOT_FOUND")

    table_rows = _table_to_rows(selected_table)
    header_index = _find_header_row(table_rows)
    if header_index < 0:
        raise PeripheralError(400, "未识别到业绩汇总表表头。", "PERFORMANCE_SUMMARY_HEADER_NOT_FOUND")
    headers = _unique_headers(table_rows[header_index])
    field_schema = [_field_schema_item(header) for header in headers]
    detail_rows: list[dict[str, Any]] = []
    for index, values in enumerate(table_rows[header_index + 1 :], start=1):
        if not _is_data_row(values):
            continue
        row_values = {
            header: _normalize_empty(values[column_index] if column_index < len(values) else "")
            for column_index, header in enumerate(headers)
        }
        core = _core_values(row_values)
        detail_rows.append(
            {
                "rowIndex": index,
                "values": row_values,
                **core,
            }
        )

    if not detail_rows:
        raise PeripheralError(400, "业绩汇总表未识别到有效明细行。", "PERFORMANCE_SUMMARY_ROWS_EMPTY")

    return {
        "categoryName": category_name,
        "scene": scene,
        "powerRating": power_rating,
        "summary": summary,
        "fieldSchema": field_schema,
        "rows": detail_rows,
        "rowCount": len(detail_rows),
        "sourceFileName": file_name,
    }


def _select_summary_table(tables: Any) -> Any | None:
    best_table = None
    best_score = -1
    for table in tables:
        rows = _table_to_rows(table)
        if not rows:
            continue
        header_index = _find_header_row(rows)
        if header_index < 0:
            continue
        header = " ".join(rows[header_index])
        score = _header_score(rows[header_index]) * 10 + max(0, len(rows) - header_index - 1)
        if any(keyword in header for keyword in ("项目", "合同", "买方", "型号")):
            score += 10
        if score > best_score:
            best_score = score
            best_table = table
    return best_table


def _table_to_rows(table: Any) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.rows:
        cells = [_clean_text(cell.text) for cell in row.cells]
        if any(cell for cell in cells):
            rows.append(cells)
    return rows


def _find_header_row(rows: list[list[str]]) -> int:
    best_index = -1
    best_score = 0
    for index, row in enumerate(rows[:8]):
        score = _header_score(row)
        non_empty = sum(1 for cell in row if cell)
        if non_empty >= 3 and score > best_score:
            best_index = index
            best_score = score
    return best_index if best_score >= 2 else -1


def _header_score(row: list[str]) -> int:
    joined = " ".join(row)
    score = 0
    for keyword in ("项目名称", "合同名称", "买方", "业主", "客户", "型号", "合同台数", "试运行", "投运容量", "联系人"):
        if keyword in joined:
            score += 1
    return score


def _infer_category_name(paragraphs: list[str], *, file_name: str) -> str:
    for paragraph in paragraphs[:6]:
        if paragraph and not paragraph.startswith("合同业绩台数"):
            return paragraph[:300]
    return Path(file_name).stem[:300]


def _infer_summary(paragraphs: list[str], *, category_name: str) -> str:
    for paragraph in paragraphs[:10]:
        if paragraph and paragraph != category_name and any(keyword in paragraph for keyword in ("合同业绩", "台数", "投运容量")):
            return paragraph
    return ""


def _infer_scene(text_value: str) -> str:
    text_value = str(text_value or "")
    if "海上" in text_value:
        return "海上"
    if "陆上" in text_value:
        return "陆上"
    return ""


def _infer_power_rating(text_value: str) -> str:
    match = re.search(r"(\d+(?:\.\d+)?)\s*MW\s*(?:及以上|以上)?", str(text_value or ""), flags=re.IGNORECASE)
    if not match:
        return ""
    suffix = "及以上" if "及以上" in match.group(0) or "以上" in match.group(0) else ""
    return f"{match.group(1)}MW{suffix}"


def _unique_headers(headers: list[str]) -> list[str]:
    result: list[str] = []
    counts: dict[str, int] = {}
    for index, header in enumerate(headers, start=1):
        value = _clean_text(header) or f"字段{index}"
        count = counts.get(value, 0) + 1
        counts[value] = count
        result.append(value if count == 1 else f"{value}_{count}")
    return result


def _field_schema_item(header: str) -> dict[str, str]:
    key = _field_key(header)
    return {"key": key, "label": header, "sourceHeader": header}


def _field_key(header: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z一-龥]+", "_", str(header or "").strip()).strip("_")
    return normalized or "field"


def _core_values(row_values: dict[str, str]) -> dict[str, str]:
    return {
        "projectName": _first_value(row_values, ("项目名称", "合同名称", "工程名称")),
        "customerName": _first_value(row_values, ("买方名称", "业主", "客户", "采购方")),
        "turbineModel": _first_value(row_values, ("型号", "机型", "风机型号")),
        "contractQuantity": _first_value(row_values, ("合同台数", "台数", "数量")),
        "trialOperationQuantity": _first_value(row_values, ("试运行台数", "240", "试运")),
        "commissionedCapacityMw": _first_value(row_values, ("投运容量", "容量")),
        "deliveryOrOperationTime": _first_value(row_values, ("交货期", "投运时间", "交付")),
        "contactInfo": _first_value(row_values, ("联系人", "电话", "联系方式")),
    }


def _first_value(row_values: dict[str, str], keywords: tuple[str, ...]) -> str:
    for key, value in row_values.items():
        if any(keyword in key for keyword in keywords):
            return value
    return ""


def _is_data_row(values: list[str]) -> bool:
    meaningful = [value for value in values if _normalize_empty(value)]
    if len(meaningful) < 2:
        return False
    joined = " ".join(meaningful)
    return not all(keyword in joined for keyword in ("序号", "型号", "项目"))


def _normalize_empty(value: Any) -> str:
    text_value = _clean_text(str(value or ""))
    if text_value in {"/", "-", "—", "无", "N/A", "NA"}:
        return ""
    return text_value


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u3000", " ")).strip()


async def _read_upload(upload: Any) -> tuple[bytes, str, str]:
    file_name = _safe_file_name(str(getattr(upload, "filename", "") or "performance.docx"))
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


def _safe_file_name(value: str) -> str:
    text_value = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    text_value = re.sub(r"\s+", " ", text_value).strip(" .")
    return text_value or "performance.docx"


performance_package_service = PerformancePackageService()
