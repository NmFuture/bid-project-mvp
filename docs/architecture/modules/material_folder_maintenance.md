# material_folder_maintenance

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_folder_maintenance.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 388 |

**职责**: 目录结构维护规则：商务标标准/定制子目录规格保障（新建客户/项目目录自动补业务子目录）、项目素材目录 bootstrap、旧版目录结构迁移（技术标旧目录、商务空遗留默认目录清理）。

## Input / Output
- Input: 目录路径/项目信息 + ensure/find 回调。
- Output: 规格化的子目录结构；旧结构迁移与空目录清理结果；`BUSINESS_EMPTY_LEGACY_DEFAULT_FOLDER_PATHS` 等清单驱动。

## 调用链
- **上游**: `material_raw_folder_operations`、`material_raw_lifecycle_operations`、`material_upload_operations`。
- **下游**: DB `raw_folders/raw_files`、`material_folder_scope`（规格与命名）、`material_taxonomy`（技术标规范路径）。

## 中间数据与状态
- 商务子目录规格清单；旧目录别名迁移规则。
