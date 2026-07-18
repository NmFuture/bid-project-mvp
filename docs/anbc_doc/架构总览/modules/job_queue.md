# job_queue

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/job_queue.py` |
| 层级 | 服务层 |
| 领域 | 解析与AI引擎 |
| 行数 | 197 |

**职责**: Redis 生成任务队列的唯一封装：入队（带项目级互斥锁）、出队、job 状态标记、锁释放。

## Input（输入）
- `enqueue_generation_job(job_type, project_id, data)`：job_type 必须 ∈ `{directory_generation, fill_generation, material_cleaning}`；data 中 `__auditUser` 被提出为 job.user。
- `dequeue_generation_job(timeout)`：worker 侧 BLPOP。

## Output（输出）
- `EnqueueResult{queued, job_id, locked, unavailable}`——同项目同类型已有任务在跑时返回 `locked=True`；Redis 不可用时 `unavailable=True`（调用方回退本地执行）。
- job 状态 hash：`queued → running → succeeded/failed`（`mark_job_status`）。

## 调用链
- **上游**: `bid_directory_flow`/`bid_generation_flow`/`material_cleaning` 的运行入口（fastapi 侧入队）、`redis_worker`（出队+状态+释放锁）。
- **下游**: `core.redis`、`core.config`。

## 中间数据与状态
- 队列 `bid:jobs`（RPUSH/BLPOP）；job hash `bid:job:{id}`（TTL 86400s）；互斥锁 `bid:lock:{jobType}:{projectId}`（SET NX，TTL 7200s，释放时校验持有者 job_id，另有 `force_release_generation_lock` 强解）。
