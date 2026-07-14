# material_identity_options

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_identity_options.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 195 |

**职责**: 「完善项目信息」身份选项组装纯函数：从素材目录/文件与项目表汇总客户与项目候选（客户名经 canonical 归一、含别名），按标类过滤排序。

## Input / Output
- Input: folders/files ORM 行 + projects 行 + bid_type。
- Output: `{customers: [...], projects: [...]}` 下拉选项。

## 调用链
- **上游**: `material_identity_options_operations`。
- **下游**: `identity`（canonical_customer/classify_material_path/build_project_identity）、`material_folder_scope`、`material_taxonomy`。

## 中间数据与状态
- 无 IO。
