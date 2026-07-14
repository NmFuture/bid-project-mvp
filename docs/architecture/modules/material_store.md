# material_store

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_store.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 大型 |

**职责**: 素材库（PostgreSQL + MinIO）的双轨共用总门面 `MaterialStore`：把 30+ 个 `material_*_operations` 模块组合成 raw（目录树/文件/上传/移动/生命周期/清洗/下载）与 wiki（节点/附件/蓝图导入）两大 API 面，所有方法按 `bid_type` 区分双轨空间。

## Input（输入）
- 每方法必带 `bid_type`（商务/技术）；上传文件、目录路径、file_id（RAW-xxxx）、wiki node_id 等。

## Output（输出）
- 目录树、文件分页列表、上传结果（含清洗任务入队 `enqueue_cleaning_job`）、下载 payload（bucket/key）、Wiki 树与节点操作结果。

## 调用链
- **上游**: `business_material_store` / `technical_material_store`（两轨门面，再被路由调用）。
- **下游**: `material_raw_*_operations`（树/文件/目录/生命周期/对象/更新/访问）、`material_upload_operations`、`material_move_operations`、`material_wiki_*_operations`、`material_runtime_tables`（建表保障）、`material_identity_options_operations`、`material_folder_scope`、`scoped_material_urls`、`models.async_session`（SQLAlchemy 会话）。

## 中间数据与状态
- PostgreSQL `raw_folders`/`raw_files`（+版本/墓碑表）与 wiki 节点表；MinIO `bid-materials`（对象 key 由 `raw_object_key` 生成，版本归档 `archive_raw_file_version`）；清洗任务走 Redis `material_cleaning` 队列；内部 URL 前缀 `INTERNAL_RAW_URL_PREFIX`。
