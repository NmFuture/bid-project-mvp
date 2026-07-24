# material_raw_tree_operations

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_raw_tree_operations.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 41 |

**职责**: 目录树查询操作：确保运行表与标类根目录存在后，全量读 `raw_folders`/`raw_files`，交给 `material_raw_tree` 组树。

## Input / Output
- Input: bid_type + 注入的 ensure 回调。Output: 目录树 payload（含 updatedAt 展示时间）。

## 调用链
- **上游**: `material_store.raw_tree`。
- **下游**: DB `raw_folders`/`raw_files`、`material_raw_tree`。

## 中间数据与状态
- 无自有状态。
