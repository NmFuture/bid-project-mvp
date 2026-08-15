# parse_s1_skill

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/parse_s1_skill.py` |
| 层级 | 服务层 |
| 领域 | 解析与AI引擎 |
| 行数 | 1085 |

**职责**: S1 解析 Skill 调用层（parsing-01 自 `parsing.py` 拆出）：prompt 构建、技术标分片并发解析与进度聚合、失败重试与本地兜底、商务 S1 finalize 守卫、opencode 轨迹/尝试记录附着。

## 关键符号
- `_run_parse_skill`、`_run_technical_sharded_parse_skill`、`_ShardProgressAggregator`、`_build_tender_parse_prompt`、`_build_technical_shard_prompt`、`_fallback_parse_skill_result`、`_finalize_business_s1_result`、`_project_basics_project_prefill`。

## 调用链
- **上游**: `parsing` 门面（re-export，`parse_tender_documents` 编排）。
- **下游**: `agent_engine`（`AgentOrchestrator`/引擎协议驱动分片会话）、s1parse CLI（`s1parse_router`）、`parse_profiles`、`parse_common`。

## 中间数据与状态
- 分片提交状态从 skill manifest 工作目录取（`_technical_submission_state`），支持断点续跑；分片并发受 `AGENT_CONCURRENCY_BUDGET` 派生预算约束。
