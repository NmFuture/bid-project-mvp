# material_upload_metadata

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_upload_metadata.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 153 |

**职责**: 上传文件的 ext_fields 构建纯函数：归属推导（目录 tier/客户/项目 + 请求参数合并）、商务类型与类别标签、初始 cleanStatus、机型名推断（`turbine_model_from_material_name`）、上传冲突动作（overwrite/version）。

## 调用链
- **上游**: `material_upload_operations`。
- **下游**: `identity`（路径分类/素材身份）、`material_taxonomy`、`material_tags`、`turbine_models`。

## 中间数据与状态
- 动作常量（upload/overwrite/version）；操作人默认「当前用户」。
