# fe_app

| | |
|---|---|
| 源文件 | `code/sewpg-bid-frontend/src/App.jsx`（+ main.jsx） |
| 层级 | 前端逻辑 |
| 领域 | 共享 |
| 行数 | ~300 |

**职责**: 应用根：会话生命周期（localStorage 读取/过期校验/持久化、`AUTH_EXPIRED_EVENT` 登出）、Toast 全局、AppShell 布局套壳、路由装配（Dashboard/Login/Settings + 三个 workspace 的 renderRoutes）。

## Input / Output
- Input: localStorage 会话、authAPI。
- Output: 登录态路由树；未登录重定向 Login；按角色进默认工作区。

## 调用链
- **上游**: main.jsx（ReactDOM 入口）。
- **下游**: `workspaces/{technical,business,shared}/routes.jsx`、`components/layout/AppShell`、`api.authAPI`、`utils/workspace`。

## 中间数据与状态
- localStorage `AUTH_STORAGE_KEY`（token/user/expiresAt）。
