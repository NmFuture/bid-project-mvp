# material_runtime_tables

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_runtime_tables.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 372 |

**职责**: 素材域运行表的幂等建表器（CREATE TABLE IF NOT EXISTS，进程内 `_ready` 标记只跑一次）：raw_folder_deletions、raw_file_versions、wiki_attachments、OCR/业绩/系统配置等运行表。

## Input / Output
- `ensure_material_runtime_tables(session)`：所有素材域操作前置调用。

## 调用链
- **上游**: `material_store`、`ocr_service`、`performance_*`、`system_settings`、`auth_service`、`audit_service`、`template_store`、`business_gap_planning`、`material_certificate_time`。
- **下游**: PostgreSQL（raw SQL text）。

## 中间数据与状态
- 建表 DDL 集中地（与 `models/materials.py` ORM 并存——DDL 在此、查询模型在彼）；`_ready` 进程缓存。
