# material_raw_lifecycle_operations

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_raw_lifecycle_operations.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 153 |

**职责**: 目录/文件生命周期操作：建目录（名称安全清洗、商务定制目录自动补子目录）、删目录（保护目录不可删、递归清理文件与 MinIO 对象、默认目录记删除墓碑）、删文件。

## Input / Output
- Input: parent_path/folder_name/path/file_id + bid_type + 注入回调（ensure 表/目录、对象清理、墓碑标记、树重载）。
- Output: 操作结果 + 最新目录树；保护路径删除抛 PeripheralError（`material_taxonomy.is_raw_material_protected_folder_path`）。

## 调用链
- **上游**: `material_store` 的 create/delete folder/file。
- **下游**: DB `raw_folders`/`raw_files`、`material_folder_maintenance`（商务定制子目录）、`material_taxonomy`（保护判定）、`material_raw_file_filter`。

## 中间数据与状态
- `raw_folder_deletions` 墓碑（默认目录被删后不再自动重建）。
