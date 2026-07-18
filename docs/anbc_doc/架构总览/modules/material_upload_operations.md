# material_upload_operations

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_upload_operations.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 317 |

**职责**: 素材上传操作总编排：目标目录规划（显式/auto）→ 目录确保（含默认目录墓碑复活）→ 后缀白名单校验 → 同名冲突处理（overwrite 归档旧版/version 存版本）→ 字节落 MinIO → ext 构建 → 记录落 DB → 清洗任务入队。

## Input / Output
- Input: 文件清单（UploadFile 流或 base64）、targetPath/tier/客户/项目/tags/onConflict。
- Output: 上传结果（成功/冲突/失败逐文件）；后缀非法抛 PeripheralError（白名单 `MATERIAL_LIBRARY_ALLOWED_SUFFIXES`）。

## 调用链
- **上游**: `material_store.raw_upload`。
- **下游**: `material_upload_target`（规划）、`material_upload_metadata`（ext）、`material_folder_maintenance`（目录确保）、`minio_client`、DB `raw_files/raw_folders`、版本归档与清洗入队回调（object_operations 注入）。

## 中间数据与状态
- 冲突动作 `{overwrite, version}`；上传即触发 cleanStatus=pending（可清洗类型）。
