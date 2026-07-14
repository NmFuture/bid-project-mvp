# material_raw_update_operations

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_raw_update_operations.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 91 |

**职责**: 素材文件更新操作：改名（安全字符清洗 + MinIO 对象同步换 key）、businessMaterialKind、tags（支持 overwrite/merge 语义，ext 构建交给 `material_update_metadata`），带标类归属校验。

## Input / Output
- Input: file_id(RAW-xxxx)/bid_type/name/kind/tags/update_tags。
- Output: 更新后的文件 dict；跨标类访问抛 PeripheralError。

## 调用链
- **上游**: `material_store.raw_update_file`。
- **下游**: DB `raw_files`、`material_update_metadata`、`material_raw_file_filter`（归属判断）、`minio_client`。

## 中间数据与状态
- ext_fields 更新；改名同步 MinIO key。
