# fe_routes_workspaces（三个 routes.jsx + WorkspaceAccess）

| | |
|---|---|
| 源文件 | `code/sewpg-bid-frontend/src/workspaces/{business,technical,shared}/routes.jsx` + `shared/WorkspaceAccess.jsx` |
| 层级 | 前端逻辑 |
| 领域 | 共享 |
| 行数 | 76+81+~40+10 |

**职责**: 双工作区路由装配。每轨 11 条路由同构：`/parse/{track}` 解析入口 → `/workspace/{slug}/projects`（列表/入口重定向）→ 项目内四段主路由 `template-directory / outline / gaps / editor` → 素材 `materials/raw|wiki`（技术标多 `certificates`）→ `logs`；业绩库两轨都重定向到 `/workspace/shared/materials/performance`。所有路由套 `WorkspaceAccess`（角色无权→跳默认工作区项目列表）。

## 调用链
- **上游**: `App.jsx`。
- **下游**: 各页面组件、`utils/permissions`。

## 中间数据与状态
- 路由形态即 README 规约：「两轨保持相同主路由形状，不再有项目级 generate/coverage/export 独立页」。
