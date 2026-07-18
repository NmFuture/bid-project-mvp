# worker_redis

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/workers/redis_worker.py` |
| 层级 | Worker |
| 领域 | 解析与AI引擎 |
| 行数 | 109 |

**职责**: 唯一的后台任务消费进程：轮询 Redis 队列取生成任务并按类型分发，管理任务状态与生成锁。

## Input（输入）
- Redis 队列中的 job：`{type, projectId, data, user}`（由 `job_queue.dequeue_generation_job` 取出）。

## Output（输出）
- 按类型执行：`directory_generation` → `bid_directory_flow._run_directory_generation_job`；`fill_generation` → `bid_generation_flow._run_fill_generation_job`（必须显式 `bidType`，经 `bid_type.require_bid_type` 校验）；`material_cleaning` → `material_cleaning.clean_material_file_sync`。
- job 状态 `mark_job_status(running → succeeded/failed)`，最终态并同步读项目运行态 `directory_state`/`fill_state` 判定失败。

## 调用链
- **上游**: docker-compose `worker` 容器（`python -m app.workers.redis_worker`）；任务由 fastapi 各生成端点入队。
- **下游**: `job_queue`、`core.redis`、`workspace_project_access.get_any_workspace_project_runtime_state`、三个任务处理模块。

## 中间数据与状态
- Redis：生成队列、job 状态 key（结果 TTL `REDIS_JOB_RESULT_TTL_SEC`=86400s）、生成锁（TTL `REDIS_JOB_LOCK_TTL_SEC`=7200s，finally 中 `release_generation_lock`）。
- SIGTERM/SIGINT 优雅退出（跑完当前 job）。
