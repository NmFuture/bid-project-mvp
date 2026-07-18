# business_document_state

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_document_state.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 25 |

**职责**: 商务标格式化结果写入 `document_state` 的纯函数：版本递增、documentKey 刷新，并记录格式化预设与摘要。

## Input / Output
- Input: 项目 dict + `format_result{preset, label, summary}`。
- Output: `document_state` 增加 `businessFormatPreset`（默认 standard）/`businessFormatLabel`/`businessFormatSummary`；`fill_state.lastBusinessFormat` 同步记录。

## 调用链
- **上游**: `bid_document_state.apply_business_document_format_to_project`。
- **下游**: 无。

## 中间数据与状态
- `document_state.businessFormat*` 字段、`fill_state.lastBusinessFormat`。
