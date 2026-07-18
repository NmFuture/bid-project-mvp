# technical_material_paths

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_material_paths.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 68 |

**职责**: 技术标素材路径规约的唯一定义：路径归一化、必须位于「技术标/」、写入根白名单 `{标准文件, 客户定制, 项目定制}`（旧别名「客户素材/项目素材」自动映射）。

## Input / Output
- `ensure_technical_material_path` / `ensure_technical_material_write_path(allow_root)` / `ensure_technical_material_new_child_path`；越界抛 `TECHNICAL_MATERIAL_PATH_REQUIRED` / `TECHNICAL_MATERIAL_WRITE_PATH_REQUIRED`(400)。

## 调用链
- **上游**: `technical_material_store`。
- **下游**: `bid_type`、`peripheral`。

## 中间数据与状态
- 常量白名单与别名映射；是三级目录（标类/档位/业务目录）规约在写入侧的守卫。
