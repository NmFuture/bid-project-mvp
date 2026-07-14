# material_move_metadata

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_move_metadata.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 84 |

**职责**: 移动操作的 ext_fields 构建纯函数：目的地 tier/标类/项目/客户归属重写、商务素材类别重推导、移动审计字段（lastAction=move/version/move-folder、操作人）。

## 调用链
- **上游**: `material_move_operations`。
- **下游**: `material_taxonomy`（类别标签/推导）、`bid_type`。

## 中间数据与状态
- ext 字段更新规则；动作常量。
