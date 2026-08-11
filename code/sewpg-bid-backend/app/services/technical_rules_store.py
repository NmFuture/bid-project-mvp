from __future__ import annotations

"""技术标规则的 SQL 存储：事实表清单（全局一份）+ 附表填写规则（按客户一份）。

- SQL 表是唯一事实来源；事实表清单每次保存后重写 override JSON
  （settings.fact_specs_override_path）作为派生缓存，load_specs() 同步消费链不动；
- 附表规则按 canonical_customer 归一出的 customer_id 存行，消费端按客户组装
  与 parse_appendix_source_matrix 输出同构的矩阵 dict，下游打分逻辑零改动；
- DDL 双写：code/initdb/01-init.sql 第 7 节与本模块 ensure 保持一致。
"""

import json
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from sqlalchemy import text

from app.models import async_session
from app.services.identity import canonical_customer
from app.services.technical_fact_spec_global import (
    apply_fact_specs_override,
    global_fact_specs_meta_path,
    load_global_fact_specs_meta,
)
from app.services.technical_fact_spec_import import EXPECTED_HEADER

# 附表规则导出列头：用词与 parse_appendix_source_matrix 的 _header_kind 识别词兼容，
# 保证导出件可再导入。
APPENDIX_RULES_EXPORT_HEADER = ["客户", "表格(附表)", "项目定制来源", "标准文件来源", "其他来源"]


class TechnicalRulesTables:
    """运行时建表（与 initdb/01-init.sql 第 7 节一致），首次访问前执行。"""

    def __init__(self) -> None:
        self._ready = False

    async def ensure(self, session: Any) -> None:
        if self._ready:
            return
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS technical_fact_spec_rows (
                    seq INTEGER PRIMARY KEY,
                    payload JSONB NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_by VARCHAR(100)
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS technical_appendix_rule_rows (
                    id BIGSERIAL PRIMARY KEY,
                    customer_id VARCHAR(80) NOT NULL,
                    customer_name VARCHAR(200) NOT NULL,
                    seq INTEGER NOT NULL,
                    table_title TEXT NOT NULL,
                    project_sources JSONB DEFAULT '[]'::jsonb,
                    standard_sources JSONB DEFAULT '[]'::jsonb,
                    other_sources JSONB DEFAULT '[]'::jsonb,
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_by VARCHAR(100),
                    UNIQUE(customer_id, seq)
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS technical_appendix_rule_meta (
                    customer_id VARCHAR(80) PRIMARY KEY,
                    customer_name VARCHAR(200) NOT NULL,
                    file_name VARCHAR(255),
                    uploaded_at TIMESTAMPTZ,
                    updated_by VARCHAR(100)
                )
                """
            )
        )
        # 调用方多是只读会话，不 commit 会连建表一起回滚（同 job_timing.ensure 的教训）；
        # 此处会话尚无其他待提交语句，提交是安全的；置位必须晚于提交。
        await session.commit()
        self._ready = True


_technical_rules_tables = TechnicalRulesTables()


async def ensure_technical_rules_tables(session: Any) -> None:
    await _technical_rules_tables.ensure(session)


def _json_list(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def resolve_customer(customer_name: Any) -> dict[str, Any]:
    """客户名 → canonical 身份；空名由调用方先行拒绝。"""
    return canonical_customer(str(customer_name or "").strip())


# ---------------------------------------------------------------------------
# 事实表清单（全局）
# ---------------------------------------------------------------------------


async def list_fact_spec_rows() -> list[dict[str, Any]]:
    """SQL 中的全局事实表清单（按行序）；从未保存过返回空列表。"""
    async with async_session() as session:
        await ensure_technical_rules_tables(session)
        result = await session.execute(
            text("SELECT payload FROM technical_fact_spec_rows ORDER BY seq")
        )
        specs: list[dict[str, Any]] = []
        for row in result:
            payload = row._mapping["payload"]
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    continue
            if isinstance(payload, dict):
                specs.append(payload)
        return specs


async def count_fact_spec_rows() -> int:
    async with async_session() as session:
        await ensure_technical_rules_tables(session)
        result = await session.execute(text("SELECT COUNT(*) FROM technical_fact_spec_rows"))
        return int(result.scalar_one() or 0)


async def _write_fact_spec_rows(session: Any, specs: list[dict[str, Any]], operator: str) -> None:
    """事务内全删全插；行序号按数组位置重排，seq 列只做排序定位。"""
    await session.execute(text("DELETE FROM technical_fact_spec_rows"))
    for index, spec in enumerate(specs, start=1):
        await session.execute(
            text(
                """
                INSERT INTO technical_fact_spec_rows (seq, payload, updated_at, updated_by)
                VALUES (:seq, CAST(:payload AS JSONB), NOW(), :updated_by)
                """
            ),
            {
                "seq": index,
                "payload": json.dumps(spec, ensure_ascii=False),
                "updated_by": operator,
            },
        )


async def store_imported_fact_spec_rows(specs: list[dict[str, Any]], operator: str) -> None:
    """Excel 导入配套的 DB 写入；override/存档/版本固化由 save_global_fact_specs 完成。"""
    async with async_session() as session:
        await ensure_technical_rules_tables(session)
        await _write_fact_spec_rows(session, specs, operator)
        await session.commit()


async def replace_fact_spec_rows(specs: list[dict[str, Any]], operator: str) -> dict[str, Any]:
    """弹窗整表保存：DB 全量替换 + 重写 override JSON（派生缓存）+ 刷新元数据 sidecar。

    override JSON 重写后 load_specs() 同步消费链立即生效，无需改任何消费端。
    """
    async with async_session() as session:
        await ensure_technical_rules_tables(session)
        await _write_fact_spec_rows(session, specs, operator)
        await session.commit()
    apply_fact_specs_override(specs)
    # 元数据 sidecar：在线保存没有新原件，保留原文件名/sha256、刷新时间/操作人
    from app.services.bid_runtime_state import now_iso

    previous = load_global_fact_specs_meta() or {}
    meta = {
        "fileName": str(previous.get("fileName") or ""),
        "uploadedAt": now_iso(),
        "uploadedBy": operator,
        "sha256": str(previous.get("sha256") or ""),
        "specTotal": len(specs),
    }
    meta_path = global_fact_specs_meta_path()
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"specTotal": len(specs)}


def export_fact_specs_xlsx(specs: list[dict[str, Any]]) -> bytes:
    """生成事实表清单 xlsx：列头与 import_specs 的导入列映射严格一致（可再导入）。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(list(EXPECTED_HEADER))
    for index, spec in enumerate(specs, start=1):
        ws.append(
            [
                spec.get("seq") or index,
                str(spec.get("targetFile") or spec.get("sourceFile") or ""),
                str(spec.get("placeholder") or ""),
                str(spec.get("label") or ""),
                str(spec.get("note") or ""),
                str(spec.get("reviewLabel") or ""),
                str(spec.get("referenceFile") or ""),
            ]
        )
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# 附表填写规则（按客户）
# ---------------------------------------------------------------------------


def _appendix_row_to_dict(row: Any) -> dict[str, Any]:
    mapping = row._mapping
    return {
        "seq": int(mapping["seq"] or 0),
        "tableTitle": str(mapping["table_title"] or ""),
        "projectSources": _json_list(mapping["project_sources"]),
        "standardSources": _json_list(mapping["standard_sources"]),
        "otherSources": _json_list(mapping["other_sources"]),
    }


async def list_appendix_rules(customer_id: str) -> list[dict[str, Any]]:
    """该客户的附表规则行（按行序）；无规则返回空列表。"""
    async with async_session() as session:
        await ensure_technical_rules_tables(session)
        result = await session.execute(
            text(
                """
                SELECT seq, table_title, project_sources, standard_sources, other_sources
                FROM technical_appendix_rule_rows
                WHERE customer_id = :customer_id
                ORDER BY seq
                """
            ),
            {"customer_id": customer_id},
        )
        return [_appendix_row_to_dict(row) for row in result]


async def appendix_rules_meta(customer_id: str) -> dict[str, Any]:
    """客户规则元数据；无行且无元数据返回 {}。"""
    async with async_session() as session:
        await ensure_technical_rules_tables(session)
        count_result = await session.execute(
            text("SELECT COUNT(*) FROM technical_appendix_rule_rows WHERE customer_id = :customer_id"),
            {"customer_id": customer_id},
        )
        row_count = int(count_result.scalar_one() or 0)
        meta_result = await session.execute(
            text(
                """
                SELECT customer_name, file_name, uploaded_at
                FROM technical_appendix_rule_meta
                WHERE customer_id = :customer_id
                """
            ),
            {"customer_id": customer_id},
        )
        meta_row = meta_result.first()
    if not row_count and meta_row is None:
        return {}
    mapping = meta_row._mapping if meta_row is not None else {}
    uploaded_at = mapping.get("uploaded_at") if meta_row is not None else None
    return {
        "rowCount": row_count,
        "fileName": str(mapping.get("file_name") or "") if meta_row is not None else "",
        "uploadedAt": uploaded_at.isoformat() if uploaded_at else "",
        "customerName": str(mapping.get("customer_name") or "") if meta_row is not None else "",
        "customerId": customer_id,
    }


async def replace_appendix_rules(
    customer_id: str,
    customer_name: str,
    rows: list[dict[str, Any]],
    operator: str,
    *,
    file_name: str | None = None,
) -> dict[str, Any]:
    """全量替换该客户的附表规则（事务内全删全插 + 元数据 upsert）。"""
    async with async_session() as session:
        await ensure_technical_rules_tables(session)
        await session.execute(
            text("DELETE FROM technical_appendix_rule_rows WHERE customer_id = :customer_id"),
            {"customer_id": customer_id},
        )
        for index, row in enumerate(rows, start=1):
            await session.execute(
                text(
                    """
                    INSERT INTO technical_appendix_rule_rows (
                        customer_id, customer_name, seq, table_title,
                        project_sources, standard_sources, other_sources,
                        updated_at, updated_by
                    )
                    VALUES (
                        :customer_id, :customer_name, :seq, :table_title,
                        CAST(:project_sources AS JSONB), CAST(:standard_sources AS JSONB),
                        CAST(:other_sources AS JSONB), NOW(), :updated_by
                    )
                    """
                ),
                {
                    "customer_id": customer_id,
                    "customer_name": customer_name,
                    "seq": index,
                    "table_title": str(row.get("tableTitle") or ""),
                    "project_sources": json.dumps(_json_list(row.get("projectSources")), ensure_ascii=False),
                    "standard_sources": json.dumps(_json_list(row.get("standardSources")), ensure_ascii=False),
                    "other_sources": json.dumps(_json_list(row.get("otherSources")), ensure_ascii=False),
                    "updated_by": operator,
                },
            )
        await session.execute(
            text(
                """
                INSERT INTO technical_appendix_rule_meta (
                    customer_id, customer_name, file_name, uploaded_at, updated_by
                )
                VALUES (:customer_id, :customer_name, :file_name, NOW(), :updated_by)
                ON CONFLICT (customer_id) DO UPDATE SET
                    customer_name = EXCLUDED.customer_name,
                    file_name = COALESCE(EXCLUDED.file_name, technical_appendix_rule_meta.file_name),
                    uploaded_at = EXCLUDED.uploaded_at,
                    updated_by = EXCLUDED.updated_by
                """
            ),
            {
                "customer_id": customer_id,
                "customer_name": customer_name,
                "file_name": file_name,
                "updated_by": operator,
            },
        )
        await session.commit()
    return {"rowCount": len(rows)}


async def load_appendix_matrix_for_customer(customer_name: Any) -> dict[str, Any]:
    """按客户组装与 parse_appendix_source_matrix 输出同构的矩阵 dict（空规则返回空 rows）。"""
    name = str(customer_name or "").strip()
    empty = {"schemaVersion": "technical-appendix-source-matrix-v1", "path": "", "rows": []}
    if not name:
        return empty
    identity = resolve_customer(name)
    customer_id = str(identity.get("customerId") or "")
    if not customer_id:
        return empty
    display_name = str(identity.get("customerCanonicalName") or name)
    rows = await list_appendix_rules(customer_id)
    return {
        "schemaVersion": "technical-appendix-source-matrix-v1",
        "path": "",
        "rows": [
            {
                "id": f"db!{customer_id}#{row['seq']}",
                "sheet": "",
                "row": row["seq"],
                "customer": display_name,
                "tableTitle": row["tableTitle"],
                "projectSources": row["projectSources"],
                "standardSources": row["standardSources"],
                "otherSources": row["otherSources"],
            }
            for row in rows
        ],
    }


def export_appendix_rules_xlsx(customer_name: str, rows: list[dict[str, Any]]) -> bytes:
    """生成该客户附表规则 xlsx：列头与解析器 _header_kind 识别词兼容（可再导入）。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "附表填写规则"
    ws.append(list(APPENDIX_RULES_EXPORT_HEADER))
    for row in rows:
        ws.append(
            [
                customer_name,
                str(row.get("tableTitle") or ""),
                "、".join(_json_list(row.get("projectSources"))),
                "、".join(_json_list(row.get("standardSources"))),
                "、".join(_json_list(row.get("otherSources"))),
            ]
        )
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
