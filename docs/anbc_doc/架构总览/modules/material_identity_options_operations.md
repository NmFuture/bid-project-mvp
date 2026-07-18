# material_identity_options_operations

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_identity_options_operations.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 44 |

**职责**: 身份选项查询操作：确保表与根目录后全量读 folders/files，并 raw SQL 读 `projects` 表（项目库未初始化时优雅跳过），交给纯函数组装。

## 调用链
- **上游**: `material_store.identity_options`（`GET /api/{track}/materials/identity-options`）。
- **下游**: DB `raw_folders/raw_files/projects`、`material_identity_options`、`material_wiki_node_operations`。

## 中间数据与状态
- 无自有状态。
