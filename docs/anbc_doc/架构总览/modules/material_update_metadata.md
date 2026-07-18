# material_update_metadata

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_update_metadata.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 38 |

**职责**: 文件更新操作的 ext_fields 构建纯函数：改名审计（sourceMinioKey/lastAction=rename）、商务素材类型（仅商务标文件可改 kind）、tags 归一化写入。

## 调用链
- **上游**: `material_raw_update_operations`。
- **下游**: `material_taxonomy`、`material_tags`。

## 中间数据与状态
- ext 字段更新规则。
