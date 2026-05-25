# 前端 API 接口总览

> 更新时间：2026-05-24
> 适用范围：`sewpg-bid-frontend` 通过双轨 API 调用正式 FastAPI。

当前前端已经从旧单线接口改为双轨接口：

```text
技术标页面 -> technical*API -> /api/technical/...
商务标页面 -> business*API -> /api/business/...
```

## 当前入口

```text
/parse/technical
/parse/business
/workspace/tech/...
/workspace/business/...
```

旧根路由和 workspace 兼容别名不再作为当前入口。

## API 封装

| 领域 | 技术标封装 | 商务标封装 |
|---|---|---|
| 项目 | `technicalProjectsAPI` | `businessProjectsAPI` |
| 阶段 | `technicalStagesAPI` | `businessStagesAPI` |
| 解析 | `technicalParseAPI` | `businessParseAPI` |
| 目录生成 | `technicalDirectoryAPI` | `businessDirectoryAPI` |
| 目录审核 | `technicalOutlineAPI` | `businessOutlineAPI` |
| 缺口 | `technicalGapsAPI` | `businessGapsAPI` |
| 生成 | `technicalGenerateAPI` | `businessGenerateAPI` |
| 文档 | `technicalDocumentAPI` | `businessDocumentAPI` |
| 素材/Wiki | `technicalMaterialsAPI` | `businessMaterialsAPI` |
| 审计 | `technicalAuditAPI` | `businessAuditAPI` |

通用封装只保留认证、设置和仪表盘：

- `authAPI`
- `settingsAPI`
- `dashboardAPI`

## 页面约定

- 技术标页面只调用 `technical*API`。
- 商务标页面只调用 `business*API`。
- 共享 UI 组件可以复用，但不能在组件内部直接调用业务 API。
- 新建/完善项目弹窗是共享 UI 壳，必须通过 `workspaceKind` 选择对应双轨 API。

## 当前事实来源

- `/Users/wlb/Agent/bid-project/code/sewpg-bid-frontend/src/api/index.js`
- `/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/api/routes/technical.py`
- `/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/api/routes/business.py`
- `/Users/wlb/Agent/bid-project/doc/31-技术标与商务标双轨独立化实施计划.md`
