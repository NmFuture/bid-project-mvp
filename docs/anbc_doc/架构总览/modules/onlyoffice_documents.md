# onlyoffice_documents

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/onlyoffice_documents.py` |
| 层级 | 服务层 |
| 领域 | 解析与AI引擎 |
| 行数 | 155 |

**职责**: OnlyOffice 文档的底层工具集：文档本地路径/MinIO key 约定、内容指纹 documentKey 生成、文档写入/确保存在/会话刷新、从 OnlyOffice 下载回存 MinIO。

## Input / Output
- `document_path(project_id)` → documents 卷 `{projectId}.docx`（评审件 `-review.docx`）。
- `document_object_key` → MinIO `documents/{projectId}/draft.docx`（review.docx 同构）。
- `build_document_key(path)`：resolve 路径+mtime+size 的 sha256 前 24 位 → OnlyOffice 缓存失效键；`build_editor_session_key(path, version)` 追加版本后缀。
- `download_document_from_onlyoffice` / `sync_document_to_minio` / `ensure_document` / `write_document`。

## 调用链
- **上游**: `bid_document_flow`、`bid_parse_service`、`tech_assembly`、`business_assembly`、两轨 document_service、`technical_document_format`、`bid_directory_flow`。
- **下游**: `minio_client`（bid-documents 桶）、httpx（OnlyOffice HTTP）、python-docx。

## 中间数据与状态
- documents 数据卷内 docx；MinIO `bid-documents`；documentKey 内容指纹（文件变则 key 变 → OnlyOffice 重新加载）。
