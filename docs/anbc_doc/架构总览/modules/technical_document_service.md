# technical_document_service

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_document_service.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 72 |

**职责**: 技术标文档服务：继承 `BidDocumentService` 底座，叠加技术格式化预设套用（`TECH_FORMAT_PRESETS`，实现走 `technical_document_format`），并同步 MinIO 与会话刷新。

## Input / Output
- Input: 共创页请求（document/save/callback/force-save/technical-format/final）。
- Output: OnlyOffice 会话、格式化后的正文与 `document_state.technicalFormat*`。

## 调用链
- **上游**: `routes/technical.py` document 端点组。
- **下游**: `bid_document_flow`、`bid_document_state`、`technical_document_format`、`onlyoffice_documents`、`workspace_project_access`。

## 中间数据与状态
- `document_state`；MinIO `documents/{pid}/draft.docx`。
