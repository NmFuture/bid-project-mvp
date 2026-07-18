# fe_api

| | |
|---|---|
| 源文件 | `code/sewpg-bid-frontend/src/api/index.js` |
| 层级 | 前端逻辑 |
| 领域 | 共享 |
| 行数 | 854 |

**职责**: 前端唯一的后端调用层：统一 request（超时 12s、重试 1 次、trace id、错误码 `HTTP_{status}`/payload.code 归一、401 广播 `AUTH_EXPIRED_EVENT`）、SSE 封装 `createEventStream`，导出 **26 个 API 组**与页面一一对应。

## API 组清单
authAPI、dashboardAPI、settingsAPI、businessProjectsAPI/StagesAPI/ParseAPI/DirectoryAPI/OutlineAPI/GapsAPI/GenerateAPI/DocumentAPI/MaterialsAPI/AuditAPI/ProjectInfoOptionsAPI、technical 同构 12 组（多 technicalStagesAPI 独立组）、performanceAPI。

## Input / Output
- Input: `ENV.API_BASE_URL`（默认 /api，nginx 反代 fastapi）、`AUTH_STORAGE_KEY` 会话 token（Authorization 头）。
- Output: 解析后的 JSON/text；FormData 自动免 Content-Type；数组查询参数展开。

## 调用链
- **上游**: 全部页面与逻辑模块。
- **下游**: 后端 `/api/*` 全部端点；SSE `technical directory /stream`。

## 中间数据与状态
- localStorage `AUTH_STORAGE_KEY` 会话；trace id 头。
