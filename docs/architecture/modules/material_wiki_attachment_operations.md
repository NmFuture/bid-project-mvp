# material_wiki_attachment_operations

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_wiki_attachment_operations.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 189 |

**职责**: Wiki 附件操作：上传（长名短化、MinIO 落桶、内部下载 URL 前缀 `INTERNAL_WIKI_URL_PREFIX`）、下载流 payload、删除（DB 记录+MinIO 对象清理）、附件序列化（大小标签等）。

## Input / Output
- Input: node_id + 文件（UploadFile/bytes）/attachment_id。
- Output: 附件记录（`wiki_attachments` 表）；下载 payload（bucket/key）。

## 调用链
- **上游**: `material_store` 的 wiki 附件三端点、`material_wiki_import/node_operations`（清理复用）。
- **下游**: DB `wiki_attachments`、`minio_client`、`filename_utils`、`scoped_material_urls`、`material_wiki_scope`。

## 中间数据与状态
- MinIO 附件对象；uuid 命名。
