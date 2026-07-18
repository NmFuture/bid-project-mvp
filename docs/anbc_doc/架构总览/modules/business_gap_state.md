# business_gap_state

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_gap_state.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 167 |

**职责**: 商务缺口运行态 `business_gap_state` 的结构保障与落账：默认字段注入、检测结果记录、计划更新收尾（含完整性统计）、素材反馈记录。

## Input / Output
- Input: 项目 dict、缺口计划。
- Output: `business_gap_state`：`{recognitionStatus: idle→…, recognizedAt, submittedForReview, reviewConfirmed, reviewedAt, plan, planFile, integrity, projectFactTable}`；`business_gap_integrity(plan)` 统计阻塞任务（status ∈ needs_input/filling/review_required）。

## 调用链
- **上游**: `business_gap_service`。
- **下游**: `bid_runtime_state.now_iso`、`business_gap_domain.update_toc_ref_statuses`、`business_gap_planning.summarize_business_gap_plan`。

## 中间数据与状态
- `business_gap_state` 全字段（项目 JSONB 内）；计划哈希（hashlib）用于变更检测。
