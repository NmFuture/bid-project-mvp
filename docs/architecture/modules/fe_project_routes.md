# fe_project_routes（business/technicalProjectRoutes.js）

| | |
|---|---|
| 源文件 | `code/sewpg-bid-frontend/src/workspaces/{business/businessProjectRoutes.js, technical/technicalProjectRoutes.js}` |
| 层级 | 前端逻辑 |
| 领域 | 共享 |
| 行数 | ~30 ×2 |

**职责**: 解析页与项目的路由纽带：`/parse/{track}?projectId=` 地址构造、解析页 projectId 选取规则（query 优先且必须存在于列表）、解析完成后是否同步路由（`shouldSync*ParseResultRoute`）。

## 调用链
- **上游**: TenderReview 解析页、ProjectList 菜单。
- **下游**: 无。
