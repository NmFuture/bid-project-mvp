# material_raw_tree

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_raw_tree.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 54 |

**职责**: 目录树 payload 组装纯函数：从 ORM 行构建嵌套树节点（folderId/path/directFileCount/递归 fileCount/children），按标类根过滤。

## 调用链
- **上游**: `material_raw_tree_operations`。
- **下游**: `material_folder_scope.MATERIAL_BID_TYPES`。

## 中间数据与状态
- 无 IO，纯内存组树。
