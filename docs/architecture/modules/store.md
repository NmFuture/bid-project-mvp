# store

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/store.py` |
| 层级 | 服务层 |
| 领域 | 基础设施与通用 |
| 行数 | 大型（项目持久化门面） |

**职责**: 底层项目持久化门面 `AppStore`：项目全量状态（含运行态）的加载/持久化/编号分配，postgres 与内存双后端。业务规则正持续迁出到 `bid_project_state` / `bid_runtime_state` 等模块（后端 README 明示）。

## Input（输入）
- `settings.project_store_backend`（默认 postgres）；项目 dict 状态（由 `bid_project_state` 系列函数构造/更新）。

## Output（输出）
- 项目字典缓存 `_projects`（postgres 模式按需 load_one 刷新）；项目编号 `PRJ-%04d` 自增分配。

## 调用链
- **上游**: `bid_project_service`（两轨项目服务的底座）、各 *_state/flow 模块经它读写项目。
- **下游**: `bid_project_repository.ProjectStateRepository`（真正的 DB 读写）、`bid_project_state`（状态构造/归一化）、`bid_runtime_state`（运行态默认值）。

## 中间数据与状态
- PostgreSQL 项目状态表（经 repository，含项目字段+各运行态 JSON）；进程内 `_projects` 缓存；`reset_for_tests` 测试钩子。
