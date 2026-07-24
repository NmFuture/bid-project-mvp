# material_raw_file_operations

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_raw_file_operations.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 62 |

**职责**: 素材文件列表查询操作：按目录（可递归 LIKE 前缀）、标题 ilike、更新时间倒序取 `raw_files`，多维过滤与分页交给 `material_raw_file_filter`。

## Input / Output
- Input: bid_type/folder_path/project_id/customer_name/material_tier/clean_status/business_material_kind/tag/title/keyword/recursive/分页。
- Output: 文件分页 payload。

## 调用链
- **上游**: `material_store.raw_files`。
- **下游**: DB `raw_files`+`raw_folders`、`material_raw_file_filter.build_raw_files_payload`。

## 中间数据与状态
- 无自有状态。
