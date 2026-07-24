# bid_document_state

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/bid_document_state.py` |
| 层级 | 服务层 |
| 领域 | 项目与状态流 |
| 行数 | 61 |

**职责**: 文档运行态 `document_state` 的纯函数更新集：保存/强制保存时递增版本并刷新 OnlyOffice documentKey，套用两轨的格式化结果。

## Input（输入）
- 项目 dict（含 `document_state`）、project_id、文档内容/格式化结果。

## Output（输出）
- 更新后的 `document_state` 深拷贝：`version` 自增、`lastSavedAt`、`onlyoffice.documentKey = {projectId}-v{n}`（key 变化驱动 OnlyOffice 换会话）、`fallback.content`。

## 调用链
- **上游**: `bid_document_flow`、`business_document_service`、`technical_document_service`。
- **下游**: `bid_runtime_state.now_iso`、`business_document_state` / `technical_document_state`（两轨格式化状态套用）。

## 中间数据与状态
- `document_state`：version / lastSavedAt / onlyoffice.documentKey / fallback.content。
