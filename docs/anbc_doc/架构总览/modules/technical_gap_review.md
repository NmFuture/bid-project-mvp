# technical_gap_review

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_gap_review.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 184 |

**职责**: 技术缺口评审视图构建：统计 resolved/skipped/pending，把每条缺口与其最新缺料提交（submissions 按 missingId 关联）拼成评审 payload。

## Input / Output
- Input: 项目 dict + gap_state（items/submissions）。
- Output: `summarize_technical_review`（三态计数）；`build_technical_review_payload`（items + 最新 submission + 评审文档状态）。

## 调用链
- **上游**: `technical_gap_service.submit_review`、`tech_assembly`（装配时的评审 payload）。
- **下游**: `technical_gap_domain`（完整性）、`technical_gap_state`、`bid_runtime_state`。

## 中间数据与状态
- 评审文档状态（gap_state 内）；item.status ∈ resolved/skipped/其余=pending。
