# material_raw_folder_operations

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_raw_folder_operations.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 228 |

**职责**: 目录结构保障类 `RawFolderOperations`：确保双轨根目录与档位目录存在（尊重删除墓碑）、路径逐级 ensure、项目素材目录 bootstrap、旧目录迁移与空目录清理。

## Input / Output
- Input: 标类/路径/项目信息 + ensure_runtime_tables 回调。
- Output: 根/档位目录 ORM 行；`ensure_folder_path` 逐级建目录；商务标准子目录回填与旧结构迁移（经 `material_folder_maintenance`）。

## 调用链
- **上游**: `material_store`（构造持有）、上传/树操作。
- **下游**: DB `raw_folders`/`raw_folder_deletions`、`material_folder_scope`（根/档位规格与元数据）、`material_folder_maintenance`、`material_taxonomy`（默认档位路径）。

## 中间数据与状态
- 双轨根目录规格（`raw_material_root_specs`）；删除墓碑跳过逻辑（商务标默认目录除外）。
