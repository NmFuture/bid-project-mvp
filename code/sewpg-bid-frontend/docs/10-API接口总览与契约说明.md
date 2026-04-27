# 10-API接口总览与契约说明

> 适用范围：`sewpg-bid-frontend` 当前正式后端入口 `../sewpg-bid-backend/app/main.py`（FastAPI）。  
> 说明：本文档用于维护前端页面所依赖的接口契约清单；当前仓库运行路径只保留正式 FastAPI 入口。  
> 版本时间：2026-04-19。

## 1. 全局约定

## 1.1 基础信息
- Base URL（开发）：`http://127.0.0.1:8000/api`
- Base URL（前端）：`/api`（通过 Vite 代理）
- Content-Type：
  - JSON 请求：`application/json`
  - 文件上传：`multipart/form-data` 或当前 FastAPI 约定的 JSON 文件元信息

## 1.2 统一错误格式
```json
{
  "detail": "错误描述",
  "code": "ERROR_CODE",
  "traceId": "trace-1710000000000"
}
```

常见错误码：
- `PROJECT_NOT_FOUND`
- `STAGE_LOCKED`
- `TIMEOUT` / `NETWORK_ERROR`
- `EXPORT_BLOCKED_BY_COVERAGE`
- `AUTH_UNAUTHORIZED`

## 1.3 现状说明
- 当前默认联调链路：前端 -> 正式 FastAPI（8000）
- 主链路真实阶段：`S0 / S1 / S2 / S3 / S7 / S8 / S9 / S10`
- 过渡 mock / 承接阶段：`S4 / S5 / S6`
- 外围模块由正式 FastAPI 承接，但其中部分数据仍属于轻量 fixture/mock 语义
- 不再支持 `__scenario / __delay / x-mock-*` 这类历史 mock 场景注入参数

## 1.4 阶段门禁
多数阶段接口会校验项目 `currentStage`：
- 若未达到目标阶段，返回 `403` + `STAGE_LOCKED`。
- 前端应在页面上提示“请先完成当前阶段”。

## 1.5 FastAPI 格式一致性（本仓）
- 前端统一请求基址：`/api`（`src/api/index.js` 统一封装）。
- 开发代理目标：`VITE_API_PROXY_TARGET=http://127.0.0.1:8000`（FastAPI）。
- 前端代码不再依赖 `3001` 端口的历史 mock 服务。

---

## 2. 认证模块（Auth）

## 2.1 登录
- **POST** `/auth/login`
- 功能：用户登录，返回 token 和用户信息。

请求体：
```json
{
  "email": "admin@sewpg.com",
  "password": "123456"
}
```

成功响应：
```json
{
  "token": "mock-token-U000-1710000000000",
  "user": {
    "id": "U000",
    "name": "管理员",
    "email": "admin@sewpg.com",
    "avatar": "管",
    "dept": "信息化中心",
    "roles": ["系统管理员"]
  },
  "expiresIn": 86400
}
```

失败：
- `400 EMAIL_REQUIRED`
- `400 PASSWORD_REQUIRED`
- `401 AUTH_INVALID_CREDENTIALS`

## 2.2 会话查询
- **GET** `/auth/me`
- 功能：查询当前登录会话（用于前端启动时恢复用户态）。

成功响应：
```json
{
  "token": "mock-token-U000-bootstrap",
  "user": {
    "id": "U000",
    "name": "管理员",
    "email": "admin@sewpg.com",
    "avatar": "管",
    "dept": "信息化中心",
    "roles": ["系统管理员"]
  }
}
```

失败：
- `401 AUTH_UNAUTHORIZED`
- `401 AUTH_TOKEN_INVALID`

## 2.3 退出
- **POST** `/auth/logout`
- 功能：清理后端会话。

响应：
```json
{ "message": "Logged out" }
```

---

## 3. 项目模块（Projects）

## 3.1 项目列表
- **GET** `/projects`
- 功能：分页查询项目。

Query 参数：
- `status`：`active/review/completed/archived/all`
- `dateRange`：`7d/30d/quarter/all`
- `page`：页码（默认 1）
- `pageSize`：每页数量（默认 12）

响应：
```json
{
  "items": [{ "id": "PRJ-2023-0891", "name": "..." }],
  "total": 6,
  "page": 1,
  "pageSize": 12
}
```

## 3.2 项目详情
- **GET** `/projects/:id`
- 功能：查询项目基础信息 + 材料路径。

响应关键字段：
- `id/name/owner/customerName/bidType`
- `currentStage/progress/completedStages/stageLabel`
- `materialsPath`
- `bidTypePaths`（技术标/商务标路径）

## 3.3 项目驾驶舱
- **GET** `/projects/:id/cockpit`
- 功能：返回驾驶舱任务列表（API 驱动，不走前端硬编码）。

响应：
```json
{
  "projectId": "PRJ-...",
  "stage": 5,
  "deadline": "2026-05-01",
  "summary": "已识别素材项 8 条，仍有 3 条待处理。",
  "tasks": [
    {
      "id": "CP-...",
      "title": "法人授权委托书",
      "desc": "未补录原因：待填写原因",
      "status": "error",
      "icon": "error",
      "actionLabel": "去处理",
      "actionRoute": "/projects/xxx/gaps-fill"
    }
  ]
}
```

## 3.4 新建项目
- **POST** `/projects`
- 功能：创建项目并初始化阶段上下文。

请求体（示例）：
```json
{
  "name": "甘肃华能100MW风电项目",
  "owner": "华能集团",
  "customerName": "华能集团",
  "manager": "张建国",
  "deadline": "2026-05-01",
  "bidType": "技术标",
  "isKeyAccount": true,
  "keyAccountId": "KA-HN"
}
```

说明：
- 新建项目阶段不再上传招标文件。
- 招标文件（必选）与模板文件（可选）统一在 S1 阶段上传。
- `manager`、`deadline`、`bidType` 后端支持默认值兜底（前端创建弹窗建议仍做必填校验）。

## 3.5 更新项目
- **PUT** `/projects/:id`
- 功能：更新项目信息（客户、负责人、标书类型等）。

## 3.6 删除项目
- **DELETE** `/projects/:id`
- 功能：删除项目及关联上下文。

响应：
```json
{ "message": "Project deleted" }
```

## 3.7 重点客户字典
- **GET** `/customers/key-accounts`
- 功能：项目创建时“重点客户”下拉选项。

## 3.8 项目素材路径
- **GET** `/projects/:id/materials-path`
- 功能：返回项目原始材料归档路径（含技术标/商务标目录）。

## 3.9 后台解析联动状态（只读）
- **GET** `/projects/:id/materials/parse-status`
- 功能：展示后端解析联动状态，前端可见不可操作。

---

## 4. 阶段状态模块（Stages）

## 4.1 阶段列表
- **GET** `/projects/:id/stages`
- 功能：返回 S1-S10 阶段状态。

## 4.2 更新阶段
- **PUT** `/projects/:id/stages/:stage`
- 功能：将某阶段置为完成，推进下一阶段。

请求体：
```json
{ "status": "completed" }
```

---

## 5. S1 解析模块

## 5.1 获取解析结果
- **GET** `/projects/:id/parse-results`
- 功能：查询解析状态、源文件、结构化条目。

## 5.2 触发解析
- **POST** `/projects/:id/parse-results/run`
- 功能：触发后端解析并返回结果。

## 5.3 上传文件并自动解析
- **POST** `/projects/:id/parse-results/upload-and-run`
- 功能：在 S1 上传招标文件（必选）+ 模板文件（可选），上传成功后自动解析并返回结果。

请求体（示例）：
```json
{
  "tenderFiles": [{ "name": "招标文件A.pdf", "size": 2097152 }],
  "templateFiles": [{ "name": "目录模板.docx", "size": 524288 }]
}
```

## 5.4 更新解析条目
- **PUT** `/projects/:id/parse-results/:rid`
- 功能：人工修正某条解析项。

---

## 6. S2 目录生成模块

## 6.1 查询目录生成状态
- **GET** `/projects/:id/directory-generation`

## 6.2 触发目录生成
- **POST** `/projects/:id/directory-generation/run`
- 返回关键字段：
  - `status=completed`
  - `output.fileName/fileType(chapterCount)`
  - `generatedAt`

---

## 7. S3 目录审核模块

## 7.1 获取目录文档
- **GET** `/projects/:id/outline`

## 7.2 保存目录
- **PUT** `/projects/:id/outline`

请求体：
```json
{
  "nodes": [
    { "id": "OL-1", "title": "第一章", "children": [] }
  ]
}
```

## 7.3 驳回重生成
- **POST** `/projects/:id/outline/regenerate`

## 7.4 确认目录
- **POST** `/projects/:id/outline/confirm`

---

## 8. S4/S5 缺口识别与补料模块

## 8.1 S4 识别状态
- **GET** `/projects/:id/gaps-detection`

## 8.2 触发识别
- **POST** `/projects/:id/gaps-detection/run`

## 8.3 S5 缺口列表
- **GET** `/projects/:id/gaps`

## 8.4 更新缺口状态
- **PUT** `/projects/:id/gaps/:gid`
- 用途：如“确认补录”。

## 8.5 上传补料（单缺口）
- **POST** `/projects/:id/gaps/:gid/upload`

## 8.6 提交审核（S5 -> S6）
- **POST** `/projects/:id/gaps/submit-review`

## 8.7 补料回执列表
- **GET** `/projects/:id/materials/submissions`

## 8.8 提交素材（支持冲突策略）
- **POST** `/projects/:id/materials/submissions`

请求体：
```json
{
  "missingId": "GAP-001",
  "bidType": "技术标",
  "onConflict": "overwrite",
  "files": [
    { "name": "授权书.docx", "size": 12345, "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }
  ]
}
```

冲突错误（409）：
- `MATERIAL_CONFLICT`

## 8.9 更新“未补录原因”
- **PATCH** `/projects/:id/materials/missing/:missingId`

请求体示例：
```json
{ "status": "skipped", "reason": "该项不适用" }
```

---

## 9. S6 审核备料模块

## 9.1 审核列表
- **GET** `/projects/:id/review-items`
- 返回：`summary + items + reviewedAt + confirmed + parse`

## 9.2 进入 S6 时触发解析
- **POST** `/projects/:id/review-items/prepare`
- 功能：在 S5 点击进入 S6 时触发后端解析，生成 S6 预览 Word。

## 9.3 S6 解析文档会话（OnlyOffice）
- **GET** `/projects/:id/review-items/document`
- 返回：`fileName/sourceFileName/version/parsedAt + onlyoffice.documentKey/title/fileUrl/callbackUrl/user`

## 9.4 S6 文档保存（兜底编辑器）
- **PUT** `/projects/:id/review-items/document/save`

请求体：
```json
{ "content": "# S6 文档内容" }
```

## 9.5 S6 强制回写
- **POST** `/projects/:id/review-items/document/force-save`

## 9.6 S6 OnlyOffice 回调
- **POST** `/projects/:id/review-items/document/callback`

## 9.7 审核确认
- **POST** `/projects/:id/review-items/confirm`
- 前置门禁：S5 已提交审核且无 pending 项。

---

## 10. S7 正文拼装模块

## 10.1 查询拼装状态
- **GET** `/projects/:id/fill-generation`

## 10.2 触发正文拼装
- **POST** `/projects/:id/fill-generation/run`
- 返回：
  - `status`
  - `runDuration/runDurationSec`
  - `filledAt`
  - `output.fileName/fileType/size`
  - `coverage`
  - `assembly`

---

## 11. S8 素材拼装覆盖校验模块

## 11.1 覆盖数据
- **GET** `/projects/:id/coverage`
- 返回：
  - `percentage/fullCover/partialCover/noCover`
  - `tree`（按素材 `scope/category` 分组的拼装覆盖树）
  - `partialItems`（未匹配目录项）
  - `noCoverItems`（未拼装素材）

---

## 12. S9 文档共创（OnlyOffice）

## 12.1 获取文档会话
- **GET** `/projects/:id/document`
- 返回：
  - `fileName/sourceFileName/version/lastSavedAt`
  - `onlyoffice.documentKey/title/fileUrl/callbackUrl/user`

## 12.2 文档保存（兜底编辑器）
- **PUT** `/projects/:id/document/save`

请求体：
```json
{ "content": "# 文档正文" }
```

## 12.3 强制回写
- **POST** `/projects/:id/document/force-save`

## 12.4 OnlyOffice 回调
- **POST** `/projects/:id/document/callback`

请求体常见字段：
```json
{
  "status": 2,
  "url": "https://doc-server/cache/edited.docx"
}
```

响应：
```json
{ "error": 0 }
```

---

## 13. S10 导出模块

## 13.1 最终文档
- **GET** `/projects/:id/final-document`
- 功能：S10 页面下载 S9 最终版。

## 13.2 导出前校验
- **GET** `/projects/:id/export/check`
- 返回：`checks/warnings/requiresWarningConfirm/suggestedFileName`

## 13.3 导出
- **POST** `/projects/:id/export`

请求体：
```json
{
  "format": "pdf",
  "fileName": "投标文件_终版_20260418",
  "warningConfirmed": true
}
```

成功：
```json
{
  "message": "Exported",
  "fileUrl": "/downloads/投标文件_终版_20260418.pdf",
  "fileName": "投标文件_终版_20260418.pdf",
  "project": { "status": "completed", "progress": 100 }
}
```

关键错误码：
- `EXPORT_BLOCKED_BY_COVERAGE`
- `EXPORT_NAME_REQUIRED`
- `EXPORT_NAME_INVALID`
- `EXPORT_WARNING_NOT_CONFIRMED`
- `EXPORT_FORMAT_INVALID`

---

## 14. 原始素材库模块（Raw）

## 14.1 权限查询
- **GET** `/materials/raw/permissions`
- Query/Header：`role` 或 `x-user-role=admin/member`

## 14.2 目录树
- **GET** `/materials/raw/tree`

## 14.3 文件列表
- **GET** `/materials/raw/files`

Query：
- `folderPath`
- `keyword`
- `bidType`
- `customerName`
- `projectId`
- `page/pageSize`

## 14.4 初始化项目目录
- **POST** `/materials/raw/folders/bootstrap`

## 14.5 新建文件夹
- **POST** `/materials/raw/folders`

请求体：
```json
{ "path": "项目素材/PRJ-2026-0001/技术标/新增目录" }
```

## 14.6 删除文件夹
- **DELETE** `/materials/raw/folders?path=...`

## 14.7 上传文件
- **POST** `/materials/raw/upload`

## 14.8 更新文件元信息
- **PATCH** `/materials/raw/:fileId`

## 14.9 移动文件
- **POST** `/materials/raw/move`

## 14.10 删除文件
- **DELETE** `/materials/raw/:fileId`

## 14.11 下载文件
- **GET** `/materials/raw/:fileId/download`

## 14.12 素材操作审计
- **GET** `/audit/material-actions`

---

## 15. 结构化素材模块（Structured）

## 15.1 列表
- **GET** `/materials/structured`

## 15.2 Excel 模板下载
- **GET** `/materials/structured/template`

## 15.3 导入预检
- **POST** `/materials/structured/import/preview`

## 15.4 导入确认
- **POST** `/materials/structured/import/confirm`

## 15.5 新增
- **POST** `/materials/structured`

## 15.6 更新
- **PUT** `/materials/structured/:id`

## 15.7 删除
- **DELETE** `/materials/structured/:id`

## 15.8 直接导入
- **POST** `/materials/structured/import`

---

## 16. Wiki 素材模块

## 16.1 列表/树/选中节点
- **GET** `/materials/wiki`

Query：
- `nodeId`（可选，指定当前选中节点）

## 16.2 新建节点/目录
- **POST** `/materials/wiki`

## 16.3 更新节点
- **PUT** `/materials/wiki/:id`

## 16.4 移动节点（拖拽）
- **POST** `/materials/wiki/:id/move`

## 16.5 上传附件
- **POST** `/materials/wiki/:id/attachments`

## 16.6 刷新 AI 摘要
- **POST** `/materials/wiki/:id/refresh-summary`

---

## 17. 审计模块

## 17.1 日志列表
- **GET** `/audit`

Query：
- `user/module/action/status`
- `keyword`
- `startDate/endDate`

## 17.2 CSV 导出
- **GET** `/audit/export`

## 17.3 日志详情（diff）
- **GET** `/audit/:id`

---

## 18. 设置中心模块

## 18.1 用户与角色
- **GET** `/settings/users`
- **POST** `/settings/users`
- **PUT** `/settings/users/:id`

## 18.2 LLM 网关
- **GET** `/settings/llm-gateway`
- **PUT** `/settings/llm-gateway`
- **POST** `/settings/llm-gateway/test`

## 18.3 dotx 模板
- **GET** `/settings/dotx-templates`
- **POST** `/settings/dotx-templates`
- **POST** `/settings/dotx-templates/:id/activate`

## 18.4 Excel 模板版本
- **GET** `/settings/excel-templates`
- **POST** `/settings/excel-templates`
- **POST** `/settings/excel-templates/:id/activate`

## 18.5 备份恢复
- **GET** `/settings/backups`
- **POST** `/settings/backups/create`
- **POST** `/settings/backups/:id/restore`

## 18.6 健康检查
- **GET** `/settings/health`

---

## 19. 前端 API 方法与后端路径映射
`src/api/index.js` 与后端路径已对齐，主要映射如下：

- `projectsAPI.list/get/create/update/delete/cockpit/materialsPath/parseStatus`
- `customersAPI.keyAccounts`
- `stagesAPI.list/update`
- `parseAPI.results/run/uploadAndRun/updateItem`
- `directoryAPI.status/run`
- `outlineAPI.get/save/regenerate/confirm`
- `gapsAPI.detectionStatus/runDetection/list/update/upload/submitReview/submissions/submitMaterial/updateMissing`
- `reviewAPI.list/prepareParse/document/saveDocument/forceSaveDocument/confirm`
- `generateAPI.status/run`
- `coverageAPI.get`
- `documentAPI.get/save/forceSave/final`
- `exportAPI.check/doExport`
- `materialsAPI.raw/structured/wiki.*`
- `auditAPI.list/detail/exportCsv`
- `settingsAPI.users/gateway/dotxTemplates/excelTemplates/backups/health`
- `authAPI.login/me/logout`

---

## 20. 建议的联调验收清单
1. 登录后顶部用户信息与后端一致。  
2. 项目列表分页、筛选结果与 `total` 一致。  
3. 任一阶段未完成时，后续阶段接口返回 `STAGE_LOCKED`。  
4. S6/S9 OnlyOffice 会话可打开、保存回写，且 S10 可下载终版。  
5. S5 补料冲突可覆盖/版本化并产生回执。  
6. 审计筛选、审计详情 diff、CSV 导出可用。  
7. 设置中心网关/模板/备份/健康接口均可回包。
