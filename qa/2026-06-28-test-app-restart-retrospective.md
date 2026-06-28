# 测试 app 重启遗漏复盘

记录时间：2026-06-28 00:16 CST

## 本次不足

- 只重启了本地 FastAPI 和 Vite，没有同时启动本地 Redis worker。
- 本地 FastAPI 启动时没有设置 `REDIS_URL`，导致素材上传虽然入库成功，但清洗任务无法投递到 Redis 队列。
- 误以为 Docker Compose 中已有 `sewpg_bid_redis` / `sewpg_bid_worker` 就覆盖了本地开发链路；实际本地后端和 Docker worker 不在同一套运行环境里。
- 没有在启动完成后检查 Redis 队列、worker 会话和 pending 清洗任务，导致 13 个 docx 长时间停留在 `cleanStatus=pending`。

## 影响

- 技术标素材上传后的 Word 清洗任务无人消费。
- 上传的 13 个 pending 文件需要事后手动重新入队。
- 用户在前端看到素材已上传，但清洗稿和 OnlyOffice 预览状态不会按预期更新。

## 正确启动清单

本地测试 app 必须至少包含四个进程/服务：

1. Redis：宿主机可访问 `127.0.0.1:6379`
2. FastAPI：带 `REDIS_URL=redis://127.0.0.1:6379/0`
3. redis worker：带同一个 `REDIS_URL=redis://127.0.0.1:6379/0`
4. Vite 前端

当前可用启动方式：

```bash
docker run -d --name nmfuture_dev_redis -p 127.0.0.1:6379:6379 redis:7-alpine redis-server --appendonly yes

tmux new-session -d -s nmfuture-backend-test -c /Users/anbc/Desktop/Nmfuture_dev_20260626/bid-project-mvp/code/sewpg-bid-backend \
  'env REDIS_URL=redis://127.0.0.1:6379/0 ONLYOFFICE_BACKEND_BASE_URL=http://host.docker.internal:8000 ./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app'

tmux new-session -d -s nmfuture-worker-test -c /Users/anbc/Desktop/Nmfuture_dev_20260626/bid-project-mvp/code/sewpg-bid-backend \
  'env REDIS_URL=redis://127.0.0.1:6379/0 ONLYOFFICE_BACKEND_BASE_URL=http://host.docker.internal:8000 ./.venv/bin/python -m app.workers.redis_worker'

tmux new-session -d -s nmfuture-frontend-test -c /Users/anbc/Desktop/Nmfuture_dev_20260626/bid-project-mvp/code/sewpg-bid-frontend \
  'npm run dev -- --host 127.0.0.1'
```

如果 `nmfuture_dev_redis` 已存在：

```bash
docker start nmfuture_dev_redis
```

## 启动后必须验证

```bash
docker exec nmfuture_dev_redis redis-cli ping
tmux list-sessions | rg 'nmfuture-(backend|frontend|worker)-test'
curl -fsS http://127.0.0.1:8000/healthz
curl -I -fsS http://127.0.0.1:5173/
docker exec nmfuture_dev_redis redis-cli llen bid:jobs
```

检查 worker 日志：

```bash
tmux capture-pane -pt nmfuture-worker-test -S -120
```

检查是否仍有待清洗素材：

```bash
cd /Users/anbc/Desktop/Nmfuture_dev_20260626/bid-project-mvp/code/sewpg-bid-backend
env REDIS_URL=redis://127.0.0.1:6379/0 ./.venv/bin/python - <<'PY'
import asyncio
from sqlalchemy import select
from app.models import async_session
from app.models.materials import RawFile

async def main():
    async with async_session() as session:
        rows = (await session.execute(select(RawFile).order_by(RawFile.id))).scalars().all()
    pending = [item for item in rows if (item.ext_fields or {}).get("cleanStatus") == "pending"]
    print("pending_count", len(pending))
    for item in pending[:50]:
        print(f"RAW-{item.id:04d}\t{item.name}")

asyncio.run(main())
PY
```

## 若发现 pending 卡住

确认 Redis 和 worker 正常后，重新投递 pending 清洗任务：

```bash
cd /Users/anbc/Desktop/Nmfuture_dev_20260626/bid-project-mvp/code/sewpg-bid-backend
env REDIS_URL=redis://127.0.0.1:6379/0 ./.venv/bin/python - <<'PY'
import asyncio
from sqlalchemy import select
from app.models import async_session
from app.models.materials import RawFile
from app.services.material_raw_object_operations import enqueue_cleaning_job

async def pending_ids():
    async with async_session() as session:
        rows = (await session.execute(select(RawFile).order_by(RawFile.id))).scalars().all()
    return [int(item.id) for item in rows if (item.ext_fields or {}).get("cleanStatus") == "pending"]

ids = asyncio.run(pending_ids())
print("pending_to_enqueue", len(ids), [f"RAW-{i:04d}" for i in ids])
for file_id in ids:
    print(f"RAW-{file_id:04d}", enqueue_cleaning_job(file_id))
PY
```

## 以后避免再犯

- 看到“完整重启测试 app”，默认包含前端、后端、Redis、worker 四件套。
- 不要只看 Docker Compose 里有 worker；本地开发后端必须和 worker 使用同一个 `REDIS_URL`。
- 启动后必须检查 `worker started` 日志和 pending 清洗数量。
- 若上传 docx 后 `cleanStatus` 长时间停在 `pending`，优先查 worker 和 Redis，而不是只查前后端端口。
