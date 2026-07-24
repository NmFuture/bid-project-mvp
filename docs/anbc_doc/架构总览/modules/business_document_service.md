# business_document_service

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_document_service.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 299 |

**职责**: 商务标文档服务：继承 `bid_document_flow.BidDocumentService` 底座，叠加商务专属 AI 三件套——共创对话（chat）、选段重写（suggest 走 LLM / apply 走受控改写）、格式化预设套用。

## Input（输入）
- 共创页请求：chat 消息、重写选段（original/replacement）、格式预设（`BUSINESS_FORMAT_PRESETS`，默认 standard）。

## Output（输出）
- OnlyOffice 会话/保存/终稿（继承底座）；chat/suggest 回复（`OpencodeClient` 即时调用）；apply 后的正文与 `document_state.businessFormat*` 更新、MinIO 同步。

## 调用链
- **上游**: `routes/business.py` document 端点组（chat/rewrite/format/save/callback/final）。
- **下游**: `bid_document_flow`、`bid_document_state`、`business_assembly`（格式预设实现）、`business_document_editing`（受控改写）、`onlyoffice_documents`、`opencode_client`、`workspace_project_access`。

## 中间数据与状态
- `document_state`（版本/格式预设记录）；MinIO `documents/{pid}/draft.docx`。
