# core_redis

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/core/redis.py` |
| 层级 | 核心配置 |
| 领域 | 系统 |
| 行数 | 44 |

**职责**: Redis 客户端单例（lru_cache）与可用性探测；redis 包缺失或未配 URL 时优雅降级为 None。

## Input / Output
- Input: `settings.redis_url`。
- Output: `get_redis_client()`（decode_responses=True，连接 2s/读写 10s 超时）；`redis_is_available()` ping 探测。

## 调用链
- **上游**: `job_queue`、`redis_worker`。
- **下游**: Redis 服务。

## 中间数据与状态
- 客户端进程级缓存。
