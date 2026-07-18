# fe_page_dashboard / login / settings

| | |
|---|---|
| 源文件 | `code/sewpg-bid-frontend/src/pages/{Dashboard.jsx(426), Login.jsx(278), Settings.jsx(767)}` |
| 层级 | 前端页面 |
| 领域 | 系统 |

**职责**:
- **Dashboard** `/dashboard`：工作台——两轨项目卡片（阶段/进度/截止）、统计；`dashboardAPI` → `GET /api/dashboard`。
- **Login** `/login`：登录表单；`authAPI.login`，成功写 localStorage 会话并按角色跳默认工作区。
- **Settings** `/settings`：用户管理、LLM 网关/OCR 配置与连通性测试、默认模板上传与激活、健康检查；`settingsAPI` → `/api/settings/*`；写操作按 `canWriteSettings`（仅 TB 角色）。

## 调用链
- **上游**: AppShell 导航。
- **下游**: `fe_api`（dashboardAPI/authAPI/settingsAPI）、`utils/permissions`。

## 中间数据与状态
- 会话 localStorage；Settings 表单态。
