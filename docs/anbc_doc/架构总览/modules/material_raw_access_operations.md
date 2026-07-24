# material_raw_access_operations

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_raw_access_operations.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 172 |

**职责**: 素材下载/预览访问操作：生成内部下载地址（`INTERNAL_RAW_URL_PREFIX/{RAW-id}/content`）、原始/清洗内容的流式 payload（bucket/key/fileName/mimeType）、OnlyOffice 清洗预览会话，均带标类归属校验。

## Input / Output
- Input: file_id + bid_type（+ 预览的 base_url 参数）。
- Output: 下载 payload / 流式 content payload（交 `api_utils.minio_streaming_response` 流出）；不存在 404 `RAW_FILE_NOT_FOUND`、跨库 400 `RAW_FILE_SCOPE`。

## 调用链
- **上游**: `material_store` 的 download/content/cleaned 系列。
- **下游**: DB `raw_files`、`material_raw_file_filter`、`scoped_material_urls`。

## 中间数据与状态
- 无自有状态；内容指纹（hashlib）用于预览会话 key。
