# bid_document_flow

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/bid_document_flow.py` |
| 层级 | 服务层 |
| 领域 | 项目与状态流 |
| 行数 | 大型 |

**职责**: 文档/OnlyOffice 的标类中性底座：编辑会话构建、回调保存、强制保存、终稿与 PDF 转换、下载主机白名单校验。business/technical document_service 各自包装。

## Input（输入）
- `project_id` + 请求；OnlyOffice 回调 payload（`oo_callback_token` 校验）；下载来源 host 需在 `ONLYOFFICE_DOWNLOAD_ALLOWED_HOSTS` 白名单。

## Output（输出）
- OnlyOffice 编辑会话配置（session key 内容指纹刷新）；文档保存（回调下载→写 MinIO `bid-documents`）；终稿 docx / PDF（转换后落盘）；`document_state`（save/force_save/final 状态，经 `bid_document_state`）。

## 调用链
- **上游**: `business_document_service` / `technical_document_service`。
- **下游**: `onlyoffice_documents`（ensure/write/sync/download 文档、会话 key）、`bid_document_state`、`bid_project_service`、`workspace_project_access`、`url_utils`、httpx（OnlyOffice HTTP）。

## 中间数据与状态
- MinIO `bid-documents` 桶对象（`document_object_key`）；`document_state`；OnlyOffice 回调 token、下载大小上限（`ONLYOFFICE_DOWNLOAD_MAX_BYTES`）。
