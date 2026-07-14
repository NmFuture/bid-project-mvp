# bid_project_repository

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/bid_project_repository.py` |
| 层级 | 服务层 |
| 领域 | 项目与状态流 |
| 行数 | 106 |

**职责**: 项目状态的持久化适配器 `ProjectStateRepository`：以同步 psycopg 直连 PostgreSQL，把整个项目状态存为 JSONB 单表；非 postgres 后端时退化为内存。

## Input（输入）
- `storage_backend`（postgres/内存）；项目 dict；归一化回调 `ProjectNormalizer`（加载时套用）。

## Output（输出）
- `ensure_db()` 建表 `projects(id VARCHAR(50) PK, state JSONB, ...)`；`load_all/load_one/persist/delete/clear`。

## 调用链
- **上游**: `store.AppStore`（唯一使用方）。
- **下游**: PostgreSQL（DSN 由 `DATABASE_URL` 改写 asyncpg→psycopg）。

## 中间数据与状态
- 表 `projects`：整个项目（含 parse/directory/fill/document 各运行态）以 JSONB 存储——项目状态的**单表 JSON 文档模型**，无按域拆表。
