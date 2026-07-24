# material_raw_object_operations

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_raw_object_operations.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 88 |

**职责**: 素材对象层操作：MinIO key 约定（`raw/{目录}/{文件名}`）、清洗产物对象删除、清洗任务入队、版本归档、对象清理——MinIO 侧失败只告警不阻断 DB 变更。

## Input / Output
- `raw_object_key(folder_path, file_name)`；`enqueue_cleaning_job(file_id)` → Redis `material_cleaning`（返回 queued/locked/unavailable）；`archive_raw_file_version` / `purge_raw_file_objects`。

## 调用链
- **上游**: `material_store`、上传/更新/删除操作模块。
- **下游**: `minio_client`（bid-materials）、`job_queue`（延迟 import 防环）、DB `RawFileVersion`。

## 中间数据与状态
- MinIO key 规约；清洗产物 key 在 ext（cleanedMinioBucket/Key）。
