from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text

from app.core.config import settings
from app.models import async_session
from app.services.bid_type import BUSINESS_BID_TYPE, TECHNICAL_BID_TYPE
from app.services.material_runtime_tables import ensure_material_runtime_tables
from app.services.material_tags import normalize_material_tags
from app.services.minio_client import minio_client
from app.services.peripheral import PeripheralError


PERFORMANCE_SCOPES = {"standard", "customer", "project"}
PERFORMANCE_REVIEW_STATUSES = {"draft", "reviewed", "disabled"}
PERFORMANCE_BID_TYPES = {BUSINESS_BID_TYPE, TECHNICAL_BID_TYPE}


class PerformanceLibraryService:
    async def list_records(
        self,
        *,
        keyword: str = "",
        customer_name: str = "",
        bid_type: str = "",
        tag: str = "",
        include_disabled: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        current_page = max(1, int(page or 1))
        current_page_size = max(1, min(100, int(page_size or 20)))
        offset = (current_page - 1) * current_page_size
        filters, params = self._filters(
            keyword=keyword,
            customer_name=customer_name,
            bid_type=bid_type,
            tag=tag,
            include_disabled=include_disabled,
        )
        where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            total_result = await session.execute(
                text(f"SELECT COUNT(*) FROM performance_records {where_sql}"),
                params,
            )
            total = int(total_result.scalar_one() or 0)
            rows = await session.execute(
                text(
                    f"""
                    SELECT *
                    FROM performance_records
                    {where_sql}
                    ORDER BY updated_at DESC, id DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {**params, "limit": current_page_size, "offset": offset},
            )
        return {
            "items": [self._row_to_dict(row._mapping) for row in rows],
            "total": total,
            "page": current_page,
            "pageSize": current_page_size,
        }

    async def create_record(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = self._normalize_payload(data, partial=False)
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            result = await session.execute(
                text(
                    """
                    INSERT INTO performance_records (
                        name, customer_name, project_type, scale, location, started_at, completed_at,
                        amount, turbine_model, tags, applicable_bid_types, scope, review_status
                    )
                    VALUES (
                        :name, :customer_name, :project_type, :scale, :location, :started_at, :completed_at,
                        :amount, :turbine_model, CAST(:tags AS JSONB), CAST(:applicable_bid_types AS JSONB),
                        :scope, :review_status
                    )
                    RETURNING *
                    """
                ),
                payload,
            )
            await session.commit()
        return {"message": "业绩记录已创建", "item": self._row_to_dict(result.first()._mapping)}

    async def update_record(self, record_id: str, data: dict[str, Any]) -> dict[str, Any]:
        numeric_id = self._numeric_id(record_id)
        payload = self._normalize_payload(data, partial=True)
        assignments = []
        params: dict[str, Any] = {"id": numeric_id}
        for key, value in payload.items():
            column = key
            if key in {"tags", "applicable_bid_types"}:
                assignments.append(f"{column} = CAST(:{key} AS JSONB)")
            else:
                assignments.append(f"{column} = :{key}")
            params[key] = value
        if not assignments:
            return {"message": "业绩记录未变更", "item": await self.get_record(record_id)}
        assignments.append("updated_at = NOW()")
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            result = await session.execute(
                text(
                    f"""
                    UPDATE performance_records
                    SET {', '.join(assignments)}
                    WHERE id = :id
                    RETURNING *
                    """
                ),
                params,
            )
            row = result.first()
            if row is None:
                raise PeripheralError(404, "业绩记录不存在。", "PERFORMANCE_NOT_FOUND")
            await session.commit()
        return {"message": "业绩记录已更新", "item": self._row_to_dict(row._mapping)}

    async def get_record(self, record_id: str) -> dict[str, Any]:
        numeric_id = self._numeric_id(record_id)
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            result = await session.execute(text("SELECT * FROM performance_records WHERE id = :id"), {"id": numeric_id})
            row = result.first()
        if row is None:
            raise PeripheralError(404, "业绩记录不存在。", "PERFORMANCE_NOT_FOUND")
        return self._row_to_dict(row._mapping)

    async def delete_record(self, record_id: str) -> dict[str, Any]:
        numeric_id = self._numeric_id(record_id)
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            result = await session.execute(
                text(
                    """
                    UPDATE performance_records
                    SET review_status = 'disabled',
                        updated_at = NOW()
                    WHERE id = :id
                    RETURNING *
                    """
                ),
                {"id": numeric_id},
            )
            row = result.first()
            if row is None:
                raise PeripheralError(404, "业绩记录不存在。", "PERFORMANCE_NOT_FOUND")
            await session.commit()
        return {"message": "业绩记录已停用", "item": self._row_to_dict(row._mapping)}

    async def list_match_candidates(
        self,
        material_scope: dict[str, Any] | None = None,
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        scope = material_scope if isinstance(material_scope, dict) else {}
        identity = scope.get("identity") if isinstance(scope.get("identity"), dict) else {}
        project_ids = _scope_values(scope, "projectId", identity.get("projectId"), identity.get("bidProjectId"))
        customer_names = _scope_values(scope, "customerName", identity.get("customerCanonicalName"), identity.get("customerName"))
        query_limit = max(1, min(500, int(limit or 200)))
        filters = [
            "review_status <> 'disabled'",
            "applicable_bid_types @> CAST(:bid_type_json AS JSONB)",
        ]
        params = {
            "bid_type_json": _json_list([BUSINESS_BID_TYPE]),
            "limit": query_limit,
        }
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            rows = await session.execute(
                text(
                    f"""
                    SELECT *
                    FROM performance_records
                    WHERE {' AND '.join(filters)}
                    ORDER BY
                        CASE review_status WHEN 'reviewed' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END,
                        updated_at DESC,
                        id DESC
                    LIMIT :limit
                    """
                ),
                params,
            )
        candidates = [
            self._row_to_material_candidate(row._mapping, material_scope=scope)
            for row in rows
        ]
        return [
            item for item in candidates
            if _candidate_matches_scope(item, customer_names=customer_names, project_ids=project_ids)
        ][:query_limit]

    async def upload_word(self, record_id: str, upload: Any) -> dict[str, Any]:
        numeric_id = self._numeric_id(record_id)
        file_name = _safe_file_name(str(getattr(upload, "filename", "") or "performance.docx"))
        if not file_name.lower().endswith((".doc", ".docx")):
            raise PeripheralError(400, "业绩库仅支持上传 Word 文件。", "PERFORMANCE_WORD_REQUIRED")
        stream = upload.file
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(0)
        if size > settings.max_upload_file_size_bytes:
            limit_mb = settings.max_upload_file_size_bytes // 1024 // 1024
            raise PeripheralError(413, f"文件超过 {limit_mb}MB 上限。", "PERFORMANCE_FILE_TOO_LARGE")
        object_key = f"performance/PERF-{numeric_id:04d}/{file_name}"
        mime_type = str(getattr(upload, "content_type", "") or "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        minio_client.put_object_stream(settings.minio_buckets["materials"], object_key, stream, size, content_type=mime_type)
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            result = await session.execute(
                text(
                    """
                    UPDATE performance_records
                    SET word_object_key = :word_object_key,
                        word_file_name = :word_file_name,
                        word_size_bytes = :word_size_bytes,
                        word_mime_type = :word_mime_type,
                        updated_at = NOW()
                    WHERE id = :id
                    RETURNING *
                    """
                ),
                {
                    "id": numeric_id,
                    "word_object_key": object_key,
                    "word_file_name": file_name,
                    "word_size_bytes": size,
                    "word_mime_type": mime_type,
                },
            )
            row = result.first()
            if row is None:
                minio_client.remove_object(settings.minio_buckets["materials"], object_key)
                raise PeripheralError(404, "业绩记录不存在。", "PERFORMANCE_NOT_FOUND")
            await session.commit()
        return {"message": "业绩 Word 已上传", "item": self._row_to_dict(row._mapping)}

    async def download_word(self, record_id: str) -> dict[str, Any]:
        item = await self.get_record(record_id)
        key = str(item.get("wordObjectKey") or "")
        if not key:
            raise PeripheralError(404, "该业绩尚未上传 Word 文件。", "PERFORMANCE_WORD_NOT_FOUND")
        return {
            "bucket": settings.minio_buckets["materials"],
            "key": key,
            "fileName": item.get("wordFileName") or f"{item['id']}.docx",
            "mimeType": item.get("wordMimeType") or "application/octet-stream",
        }

    def _filters(
        self,
        *,
        keyword: str,
        customer_name: str,
        bid_type: str,
        tag: str,
        include_disabled: bool,
    ) -> tuple[list[str], dict[str, Any]]:
        filters: list[str] = []
        params: dict[str, Any] = {}
        if not include_disabled:
            filters.append("review_status <> 'disabled'")
        kw = str(keyword or "").strip()
        if kw:
            filters.append(
                "("
                "name ILIKE :keyword OR customer_name ILIKE :keyword OR project_type ILIKE :keyword OR "
                "scale ILIKE :keyword OR location ILIKE :keyword OR amount ILIKE :keyword OR turbine_model ILIKE :keyword"
                ")"
            )
            params["keyword"] = f"%{kw}%"
        customer = str(customer_name or "").strip()
        if customer:
            filters.append("customer_name ILIKE :customer_name")
            params["customer_name"] = f"%{customer}%"
        requested_bid_type = str(bid_type or "").strip()
        if requested_bid_type:
            filters.append("applicable_bid_types @> CAST(:bid_type_json AS JSONB)")
            params["bid_type_json"] = _json_list([requested_bid_type])
        requested_tag = str(tag or "").strip()
        if requested_tag:
            filters.append("tags @> CAST(:tag_json AS JSONB)")
            params["tag_json"] = _json_list([requested_tag])
        return filters, params

    def _normalize_payload(self, data: dict[str, Any], *, partial: bool) -> dict[str, Any]:
        fields = {
            "name": "name",
            "customerName": "customer_name",
            "projectType": "project_type",
            "scale": "scale",
            "location": "location",
            "startedAt": "started_at",
            "completedAt": "completed_at",
            "amount": "amount",
            "turbineModel": "turbine_model",
            "scope": "scope",
            "reviewStatus": "review_status",
        }
        payload: dict[str, Any] = {}
        for source, target in fields.items():
            if source in data or not partial:
                payload[target] = str(data.get(source) or "").strip()
        if "name" in payload and not payload["name"]:
            raise PeripheralError(400, "业绩名称不能为空。", "PERFORMANCE_NAME_REQUIRED")
        if "scope" in payload:
            payload["scope"] = payload["scope"] if payload["scope"] in PERFORMANCE_SCOPES else "standard"
        if "review_status" in payload:
            status = payload["review_status"] or "draft"
            payload["review_status"] = status if status in PERFORMANCE_REVIEW_STATUSES else "draft"
        if "tags" in data or not partial:
            payload["tags"] = _json_list(normalize_material_tags(data.get("tags")))
        if "applicableBidTypes" in data or not partial:
            bid_types = [item for item in normalize_material_tags(data.get("applicableBidTypes")) if item in PERFORMANCE_BID_TYPES]
            payload["applicable_bid_types"] = _json_list(bid_types or [BUSINESS_BID_TYPE])
        return payload

    def _row_to_dict(self, row: Any) -> dict[str, Any]:
        row_dict = dict(row)
        numeric_id = int(row_dict.get("id") or 0)
        return {
            "id": f"PERF-{numeric_id:04d}",
            "name": row_dict.get("name") or "",
            "customerName": row_dict.get("customer_name") or "",
            "projectType": row_dict.get("project_type") or "",
            "scale": row_dict.get("scale") or "",
            "location": row_dict.get("location") or "",
            "startedAt": row_dict.get("started_at") or "",
            "completedAt": row_dict.get("completed_at") or "",
            "amount": row_dict.get("amount") or "",
            "turbineModel": row_dict.get("turbine_model") or "",
            "tags": list(row_dict.get("tags") or []),
            "applicableBidTypes": list(row_dict.get("applicable_bid_types") or []),
            "scope": row_dict.get("scope") or "standard",
            "wordObjectKey": row_dict.get("word_object_key") or "",
            "wordFileName": row_dict.get("word_file_name") or "",
            "wordSizeBytes": int(row_dict.get("word_size_bytes") or 0),
            "wordMimeType": row_dict.get("word_mime_type") or "",
            "cleanedObjectKey": row_dict.get("cleaned_object_key") or "",
            "reviewStatus": row_dict.get("review_status") or "draft",
            "createdAt": row_dict.get("created_at").isoformat() if row_dict.get("created_at") else "",
            "updatedAt": row_dict.get("updated_at").isoformat() if row_dict.get("updated_at") else "",
        }

    def _row_to_material_candidate(self, row: Any, *, material_scope: dict[str, Any]) -> dict[str, Any]:
        item = self._row_to_dict(row)
        tags = [str(tag) for tag in item.get("tags") or [] if str(tag).strip()]
        title = item["name"] or item["id"]
        customer = item.get("customerName") or ""
        path_parts = ["商务标", "共用业绩库"]
        if customer:
            path_parts.append(customer)
        path_parts.append(title)
        scope = str(item.get("scope") or "standard")
        summary_parts = [
            item.get("customerName"),
            item.get("projectType"),
            item.get("scale"),
            item.get("location"),
            item.get("amount"),
            item.get("startedAt"),
            item.get("completedAt"),
            item.get("turbineModel"),
        ]
        return {
            **item,
            "id": item["id"],
            "materialId": item["id"],
            "name": title,
            "fileName": item.get("wordFileName") or title,
            "folderPath": "/".join(path_parts[:-1]),
            "path": "/".join(path_parts),
            "materialTier": scope,
            "libraryScope": scope,
            "businessMaterialKind": "performance",
            "businessMaterialKindLabel": "共用业绩",
            "sourceType": "performance_library",
            "candidateType": "performance_record",
            "cleanStatus": "original_only" if item.get("wordObjectKey") else "metadata_only",
            "hasCleanedWord": False,
            "tags": tags,
            "keywords": _performance_keywords(item, tags),
            "summary": "；".join(str(part).strip() for part in summary_parts if str(part or "").strip()),
            "businessCategory": "业绩证明",
            "documentType": "业绩记录",
            "reviewStatus": item.get("reviewStatus") or "draft",
            "scope": scope,
            "materialScope": material_scope,
        }

    def _numeric_id(self, record_id: str) -> int:
        try:
            return int(str(record_id or "").replace("PERF-", ""))
        except ValueError as exc:
            raise PeripheralError(400, "业绩记录 ID 无效。", "PERFORMANCE_ID_INVALID") from exc


def _json_list(values: list[str]) -> str:
    import json

    return json.dumps(values, ensure_ascii=False)


def _safe_file_name(value: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or "performance.docx"


def _scope_values(scope: dict[str, Any], key: str, *fallbacks: Any) -> list[str]:
    values: list[str] = []
    for readable in scope.get("readableScopes") or []:
        if isinstance(readable, dict):
            values.append(str(readable.get(key) or ""))
    values.extend(str(value or "") for value in fallbacks)
    return [value for value in normalize_material_tags(values) if value]


def _candidate_matches_any_project(item: dict[str, Any], project_ids: list[str]) -> bool:
    text = " ".join(
        str(item.get(key) or "")
        for key in ("name", "summary", "path", "projectType", "customerName", "tags", "keywords")
    )
    return any(project_id and project_id in text for project_id in project_ids)


def _candidate_matches_scope(item: dict[str, Any], *, customer_names: list[str], project_ids: list[str]) -> bool:
    scope = str(item.get("scope") or item.get("libraryScope") or "standard")
    if scope == "standard":
        return True
    if scope == "customer":
        if not customer_names:
            return False
        item_customer = str(item.get("customerName") or "")
        return any(customer and customer in item_customer or item_customer and item_customer in customer for customer in customer_names)
    if scope == "project":
        return bool(project_ids) and _candidate_matches_any_project(item, project_ids)
    return False


def _performance_keywords(item: dict[str, Any], tags: list[str]) -> list[str]:
    values = [
        "业绩",
        "业绩证明",
        "合同",
        "中标",
        item.get("name"),
        item.get("customerName"),
        item.get("projectType"),
        item.get("scale"),
        item.get("location"),
        item.get("turbineModel"),
        *tags,
    ]
    return normalize_material_tags(values)


performance_library_service = PerformanceLibraryService()
