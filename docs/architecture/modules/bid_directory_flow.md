# bid_directory_flow

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/bid_directory_flow.py` |
| 层级 | 服务层 |
| 领域 | 项目与状态流 |
| 行数 | 大型 |

**职责**: 目录（大纲）生成的标类中性底座：发起生成（优先入 Redis 队列，锁检查）、worker 侧执行 `_run_directory_generation_job`、进度事件、目录读写/确认、招标原文 OnlyOffice 预览。business/technical directory_service 各自包装它。

## Input（输入）
- `project_id` + 生成参数；项目解析输入件（`project_parse_input_records`）。
- 三步任务模型：`准备目录候选 → futurecode 语义审核 → 保存审核目录`。

## Output（输出）
- `directory_state`（经 `bid_outline_state`：start→update→confirm/fail，含规则证据 rule_evidence 与 opencode 轨迹）；目录 JSON（toc.json）；SSE/轮询用进度事件。

## 调用链
- **上游**: `business_directory_service` / `technical_directory_service`（路由再包一层）、`redis_worker`（job 执行）。
- **下游**: `outline_generation`（真正生成）、`job_queue`（入队+锁）、`bid_outline_state`、`bid_project_service/state`、`onlyoffice_documents`、`workspace_project_access`、`url_utils`。

## 中间数据与状态
- Redis 队列 job `directory_generation` + 锁 `bid:lock:directory_generation:{projectId}`；`directory_state`（tasks 三步状态、events、opencodeOutput）；workspace 内 toc.json。
