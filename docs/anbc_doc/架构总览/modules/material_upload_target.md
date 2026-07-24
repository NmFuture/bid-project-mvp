# material_upload_target

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_upload_target.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 127 |

**职责**: 上传目标目录规划纯函数：显式 targetPath 与「auto 模式」（按标类+档位+项目/客户自动推导落点）两种模式，非法输入返回带 code 的 error 计划。

## Input / Output
- `build_raw_upload_target_plan(target_path, project_id, customer_name, bid_type, material_tier)` → `{mode: explicit|auto|error, code, bidType, materialTier, targetPath}`。

## 调用链
- **上游**: `material_upload_operations`。
- **下游**: `identity.classify_material_path`、`material_taxonomy`、`scoped_material_urls`。

## 中间数据与状态
- 无。
