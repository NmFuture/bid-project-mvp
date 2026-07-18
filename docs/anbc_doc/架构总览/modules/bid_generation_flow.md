# bid_generation_flow

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/bid_generation_flow.py` |
| 层级 | 服务层 |
| 领域 | 项目与状态流 |
| 行数 | 大型 |

**职责**: 正文/填写生成（fill_generation）的标类中性底座：按标类路由到商务/技术草稿生成器与装配 Skill，管理生成状态与审计。

## Input（输入）
- `project_id` + 请求数据；标类解析优先级：请求 `__bidType` > 项目 `bidType`（必须显式，`require_bid_type` 把关）。
- 标类上下文：商务 → Skill `bid-business-assembler`（商务标响应文件装配）；技术 → Skill `bid-tech-assembler`（技术标正文拼装）。

## Output（输出）
- `fill_state`（`bid_fill_generation_state`：start→update→fail；陈旧判定 1h `FILL_GENERATION_STALE_AFTER_SEC`）；生成产物（正文 docx，经各轨 draft_generation）；审计记录。

## 调用链
- **上游**: `business_generation_service` / `technical_generation_service`（路由包装）、`redis_worker`（`_run_fill_generation_job`）。
- **下游**: `business_draft_generation` / `technical_draft_generation`（带进度回调的生成器）、`job_queue`（入队/锁/强制解锁）、`bid_fill_generation_state`、`audit_service`、`workspace_project_access`。

## 中间数据与状态
- Redis job `fill_generation` + 锁；`fill_state`（status/tasks/events）；生成上下文标签（skill/taskLabel/documentLabel）。
