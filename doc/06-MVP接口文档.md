# 双轨 API 接口文档

> 当前业务接口基线。
> 更新日期：2026-05-26

## 1. 总原则

技术标和商务标不再共用旧单线业务接口。当前核心业务接口按 workspace 分成两组：

```text
技术标：/api/technical/...
商务标：/api/business/...
```

可以共享的接口：

- 认证：`/api/auth/...`
- 设置：`/api/settings/...`
- 系统健康：`/api/healthz`、`/api/system/...`
- 仪表盘：`/api/dashboard/...`

## 2. 技术标接口族

| 模块 | 路由前缀 |
|---|---|
| 项目列表、新建、详情、更新、删除 | `/api/technical/projects` |
| 阶段 | `/api/technical/projects/{project_id}/stages` |
| 项目素材范围 | `/api/technical/projects/{project_id}/materials-path` |
| 模板 fallback | `/api/technical/projects/{project_id}/template-fallback` |
| 解析 | `/api/technical/projects/{project_id}/parse-results` |
| OCR | `/api/technical/projects/{project_id}/ocr` |
| 目录生成 | `/api/technical/projects/{project_id}/directory-generation` |
| 目录审核 | `/api/technical/projects/{project_id}/outline` |
| 缺口识别和处理 | `/api/technical/projects/{project_id}/gaps` |
| 正文生成 | `/api/technical/projects/{project_id}/fill-generation` |
| 共创文档 | `/api/technical/projects/{project_id}/document` |
| 最终文档和下载 | `/api/technical/projects/{project_id}/final-document` |
| 后端诊断/兼容交付 | `/api/technical/projects/{project_id}/coverage`、`/api/technical/projects/{project_id}/export` |
| 素材库和 Wiki | `/api/technical/materials` |
| 审计 | `/api/technical/audit` |

## 3. 商务标接口族

| 模块 | 路由前缀 |
|---|---|
| 项目列表、新建、详情、更新、删除 | `/api/business/projects` |
| 阶段 | `/api/business/projects/{project_id}/stages` |
| 项目素材范围 | `/api/business/projects/{project_id}/materials-path` |
| 模板 fallback | `/api/business/projects/{project_id}/template-fallback` |
| 解析 | `/api/business/projects/{project_id}/parse-results` |
| OCR | `/api/business/projects/{project_id}/ocr` |
| 目录生成 | `/api/business/projects/{project_id}/directory-generation` |
| 目录审核 | `/api/business/projects/{project_id}/outline` |
| 商务缺口 | `/api/business/projects/{project_id}/business-gaps` |
| 商务文档 | `/api/business/projects/{project_id}/document` |
| 素材库和 Wiki | `/api/business/materials` |
| 审计 | `/api/business/audit` |

## 4. 前端调用规则

前端业务页面只调用双轨封装：

- 技术标页面：`technicalProjectsAPI`、`technicalParseAPI`、`technicalDirectoryAPI`、`technicalOutlineAPI`、`technicalGapsAPI`、`technicalGenerateAPI`、`technicalDocumentAPI`、`technicalMaterialsAPI`、`technicalAuditAPI`
- 商务标页面：`businessProjectsAPI`、`businessParseAPI`、`businessDirectoryAPI`、`businessOutlineAPI`、`businessGapsAPI`、`businessGenerateAPI`、`businessDocumentAPI`、`businessMaterialsAPI`、`businessAuditAPI`

共享 UI 组件不能直接调用业务 API，必须由页面传入 workspace 语义或回调。

前端当前不再使用技术标独立覆盖/导出 API 封装；`coverage` / `export` 仅作为技术标后端诊断或外围兼容交付能力保留，不对应独立前端页面，Word/PDF 下载走 `technicalDocumentAPI.final*`。

## 5. 权限与鉴权边界

当前代码区分三类登录角色：

| 角色 | 示例账号 | 工作区 |
|---|---|---|
| `T` | 安博 | 技术标 |
| `B` | 马哥 | 商务标 |
| `TB` | 肖哥 | 技术标 + 商务标 |

已实现的边界：

- 登录 token 与 `/api/auth/me` 可确认当前用户。
- 前端通过 `permissions.js` 和 `WorkspaceAccess` 限制 workspace 路由可见性。
- `/api/dashboard` 会按 `T/B/TB` 返回技术标、商务标或双线并列项目。

尚未闭环的生产级边界：

- `current_user` 只校验 token，不校验角色能否访问对应 workspace。
- `/api/business/...` 和 `/api/technical/...` 还没有统一挂载角色依赖；项目级接口也需要继续校验 `project.bidType` 与当前路由、用户角色一致。
- `/api/settings/...` 当前只要求登录，还没有限制为 `TB`。

因此当前 API 文档只能说明“接口已双轨化”，不能把它理解为“后端权限已经生产级隔离”。权限加固路线见 `doc/27-双轨开发协作规范与权限加固计划.md`。

## 6. 权威代码位置

- `/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/api/routes/technical.py`
- `/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/api/routes/business.py`
- `/Users/wlb/Agent/bid-project/code/sewpg-bid-frontend/src/api/index.js`
- `/Users/wlb/Agent/bid-project/doc/31-技术标与商务标双轨独立化实施计划.md`
