# business_draft_generation

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_draft_generation.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 20 |

**职责**: 商务标正文生成入口的转发薄层：`generate_business_draft_for_project(_with_progress)` 直接委托 `business_assembly.assemble_business_bid_for_project_with_progress`。

## Input / Output
- Input: project_id + data + 可选进度回调。
- Output: 装配结果（透传）。

## 调用链
- **上游**: `bid_generation_flow`（fill_generation 按标类分发）。
- **下游**: `business_assembly`。

## 中间数据与状态
- 无。
