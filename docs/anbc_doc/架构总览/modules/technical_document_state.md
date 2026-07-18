# technical_document_state

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_document_state.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 25 |

**职责**: 技术标格式化结果写入 `document_state` 的纯函数：版本递增、documentKey 刷新、记录 `technicalFormatPreset/Label/Summary`，`fill_state.lastTechnicalFormat` 同步。与商务侧完全对称。

## 调用链
- **上游**: `bid_document_state.apply_technical_document_format_to_project`。
- **下游**: 无。

## 中间数据与状态
- `document_state.technicalFormat*`、`fill_state.lastTechnicalFormat`。
