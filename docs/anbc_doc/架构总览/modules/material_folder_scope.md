# material_folder_scope

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_folder_scope.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 254 |

**职责**: 素材空间规约的中心定义：双轨标类集合、档位目录命名与排序（standard 通用素材/customer 客户素材/project 项目素材——注意与技术标写入名「标准文件/客户定制/项目定制」的映射在 taxonomy/paths 侧）、移动保护路径、项目素材根路径推导、目录元数据规范化。

## Input / Output
- `normalize/require_material_bid_type`；`material_tier_*` 命名与排序；`project_material_root_path(project)`（缺口上传/事实素材的落点）；`infer_material_tier_from_raw_folder`；`raw_material_root_specs`（根/档位规格）。

## 调用链
- **上游**: `material_store`、`material_raw_*`、`material_folder_maintenance`、`business/technical gap 域`、`peripheral`。
- **下游**: `bid_type`、`identity.classify_material_path`、`material_taxonomy`（目录常量与保护判定）。

## 中间数据与状态
- 常量：`MATERIAL_BID_TYPES`、`TIER_FOLDER_NAMES/SORT_ORDER`、`RAW_PERMISSION_ACTIONS`。
