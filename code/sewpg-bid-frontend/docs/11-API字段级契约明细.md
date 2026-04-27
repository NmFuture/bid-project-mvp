# 11-API字段级契约明细

> 项目：`sewpg-bid-frontend`  
> 后端入口：`../sewpg-bid-backend/app/main.py`（FastAPI）  
> 说明：本文档主要维护前端字段依赖与接口对象形状；当前仓库运行路径只保留正式 FastAPI。  
> 更新时间：2026-04-19

## 1. 全局规范

## 1.1 基础地址
- 开发直连：`http://127.0.0.1:8000/api`
- 前端调用：`/api`（通过 Vite 代理）

## 1.2 通用错误对象
```json
{
  "detail": "错误描述",
  "code": "ERROR_CODE",
  "traceId": "trace-1710000000000"
}
```

字段说明：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `detail` | `string` | 是 | 面向前端展示的错误描述 |
| `code` | `string` | 是 | 机器可识别错误码 |
| `traceId` | `string` | 否 | 链路追踪 ID |

## 1.3 现状说明
- 当前默认请求链路为：前端 -> 正式 FastAPI（8000）
- 主链路阶段与外围模块都由正式 FastAPI 统一承接
- 部分外围模块当前仍返回轻量 fixture/mock 语义数据，用于支撑页面、联调和演示
- 不再支持 `__scenario / __delay / x-mock-*` 这类历史 mock 参数

## 1.4 前端 API 客户端约定
- 统一透传 `x-trace-id`
- GET 请求支持重试
- 支持超时与取消
- 统一将错误归一到 `ApiError`

## 1.5 FastAPI 格式一致性（本仓）
- 前端业务请求统一走 `/api`（见 `src/api/index.js`）。
- Vite 代理默认转发到 `http://127.0.0.1:8000`（FastAPI 入口）。
- 代码内不再依赖 `3001` 的历史 mock 服务。

---

## 2. Auth 认证模块

## 2.1 `POST /auth/login`
功能：登录并建立会话。

请求体：
| 字段 | 类型 | 必填 | 枚举/约束 | 说明 |
|---|---|---:|---|---|
| `email` | `string` | 是 | 非空，邮箱格式建议 | 登录邮箱 |
| `password` | `string` | 是 | 非空 | 登录密码 |

成功响应字段：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `token` | `string` | 是 | 会话 token |
| `user.id` | `string` | 是 | 用户 ID |
| `user.name` | `string` | 是 | 用户名 |
| `user.email` | `string` | 是 | 邮箱 |
| `user.avatar` | `string` | 是 | 头像字符 |
| `user.dept` | `string` | 否 | 部门 |
| `user.roles` | `string[]` | 否 | 角色列表 |
| `expiresIn` | `number` | 是 | 有效秒数 |

错误码：`EMAIL_REQUIRED`、`PASSWORD_REQUIRED`、`AUTH_INVALID_CREDENTIALS`

## 2.2 `GET /auth/me`
功能：获取当前登录态。

请求：无。可选 Header：
| Header | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `Authorization` | `string` | 否 | `Bearer <token>` |

成功响应：`token + user`（字段与登录返回一致）。

错误码：`AUTH_UNAUTHORIZED`、`AUTH_TOKEN_INVALID`

## 2.3 `POST /auth/logout`
功能：清理当前会话。

成功响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `message` | `string` | 是 | 固定 `Logged out` |

---

## 3. Projects 项目模块

## 3.1 `GET /projects`
功能：分页查询项目。

Query 参数：
| 参数 | 类型 | 必填 | 枚举/约束 | 说明 |
|---|---|---:|---|---|
| `status` | `string` | 否 | `active/review/completed/archived/all` | 状态筛选 |
| `dateRange` | `string` | 否 | `7d/30d/quarter/all` | 时间筛选 |
| `page` | `number` | 否 | `>=1` | 页码 |
| `pageSize` | `number` | 否 | `1~50` | 每页数量 |

成功响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `items` | `Project[]` | 是 | 当前页项目 |
| `total` | `number` | 是 | 总条数 |
| `page` | `number` | 是 | 当前页 |
| `pageSize` | `number` | 是 | 每页数 |

`Project` 关键字段：
| 字段 | 类型 | 必有 | 枚举/约束 | 说明 |
|---|---|---:|---|---|
| `id` | `string` | 是 | `PRJ-*` | 项目 ID |
| `name` | `string` | 是 |  | 项目名 |
| `owner` | `string` | 是 |  | 业主/客户 |
| `customerName` | `string` | 是 |  | 客户名 |
| `isKeyAccount` | `boolean` | 是 |  | 是否重点客户 |
| `keyAccountId` | `string` | 否 |  | 重点客户 ID |
| `bidType` | `string` | 是 | `技术标/商务标` | 标书类型 |
| `manager` | `string` | 是 |  | 负责人 |
| `managerAvatar` | `string` | 是 |  | 头像字 |
| `createdAt` | `string` | 是 | `YYYY-MM-DD` | 创建日期 |
| `deadline` | `string` | 是 | `YYYY-MM-DD` | 截止日期 |
| `status` | `string` | 是 | `active/review/completed/archived` | 状态 |
| `currentStage` | `number` | 是 | `1~10` | 当前阶段 |
| `stageLabel` | `string` | 是 |  | 阶段文案 |
| `progress` | `number` | 是 | `0~100` | 总进度 |
| `completedStages` | `number` | 是 | `0~10` | 已完成阶段数 |
| `files` | `string[]` | 是 |  | 当前项目已关联的招标文件名（通常在 S1 上传） |

## 3.2 `GET /projects/:id`
功能：查询项目详情（含材料路径）。

Path 参数：
| 参数 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `id` | `string` | 是 | 项目 ID |

响应在 `Project` 基础上新增：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `materialsPath` | `string` | 是 | 项目材料根路径 |
| `bidTypePaths.技术标` | `string` | 是 | 技术标路径 |
| `bidTypePaths.商务标` | `string` | 是 | 商务标路径 |

错误码：`PROJECT_NOT_FOUND`

## 3.3 `GET /projects/:id/cockpit`
功能：驾驶舱任务数据（前端不再硬编码）。

响应字段：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `projectId` | `string` | 是 | 项目 ID |
| `stage` | `number` | 是 | 当前阶段 |
| `deadline` | `string` | 是 | 截止日期 |
| `summary` | `string` | 是 | 驾驶舱摘要 |
| `tasks` | `CockpitTask[]` | 是 | 任务列表 |

`CockpitTask`：
| 字段 | 类型 | 必有 | 枚举 | 说明 |
|---|---|---:|---|---|
| `id` | `string` | 是 |  | 任务 ID |
| `title` | `string` | 是 |  | 任务标题 |
| `desc` | `string` | 是 |  | 描述 |
| `status` | `string` | 是 | `done/error` | 任务状态 |
| `icon` | `string` | 否 |  | 图标名 |
| `actionLabel` | `string` | 否 |  | 按钮文案 |
| `actionRoute` | `string` | 否 |  | 前端跳转路由 |

## 3.4 `POST /projects`
功能：创建项目并初始化项目目录上下文。

请求体：
| 字段 | 类型 | 必填 | 枚举/约束 | 说明 |
|---|---|---:|---|---|
| `name` | `string` | 否 | 前端建议必填 | 项目名 |
| `owner` | `string` | 否 |  | 业主（可由 `customerName` 兜底） |
| `customerName` | `string` | 否 |  | 客户名 |
| `manager` | `string` | 否 | 默认 `未分配` | 负责人 |
| `deadline` | `string` | 否 | `YYYY-MM-DD`，默认当天 | 截止日期 |
| `bidType` | `string` | 否 | `技术标/商务标` | 默认技术标 |
| `isKeyAccount` | `boolean` | 否 |  | 是否重点客户 |
| `keyAccountId` | `string` | 否 |  | 重点客户 ID |
| `files` | `string[]` | 否 |  | 兼容字段，建议在 S1 上传接口传入 |
| `templateFiles` | `string[]` | 否 |  | 兼容字段，建议在 S1 上传接口传入 |

成功响应：`Project + materialsPath + bidTypePaths`

## 3.5 `PUT /projects/:id`
功能：更新项目基础信息（禁止直接前跳阶段）。

请求体常用字段：`name/owner/customerName/isKeyAccount/keyAccountId/bidType/manager/deadline/status/files`。

特殊错误：
- `STAGE_UPDATE_FORBIDDEN`（尝试用此接口推进阶段）

## 3.6 `DELETE /projects/:id`
功能：删除项目与关联上下文。

成功响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `message` | `string` | 是 | `Project deleted` |
| `item` | `Project` | 是 | 被删除项目 |

## 3.7 `GET /customers/key-accounts`
功能：重点客户字典。

响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `items[].id` | `string` | 是 | 客户 ID |
| `items[].name` | `string` | 是 | 客户名称 |
| `items[].folderPath` | `string` | 是 | 客户材料目录 |

## 3.8 `GET /projects/:id/materials-path`
功能：获取项目材料路径。

响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `projectId` | `string` | 是 | 项目 ID |
| `archiveType` | `string` | 是 | `客户素材/项目素材` |
| `basePath` | `string` | 是 | 根路径 |
| `customerName` | `string` | 是 | 客户名 |
| `isKeyAccount` | `boolean` | 是 | 是否重点客户 |
| `bidTypePaths` | `object` | 是 | 技术标/商务标子路径 |

## 3.9 `GET /projects/:id/materials/parse-status`
功能：展示后台解析联动状态（只读）。

响应：
| 字段 | 类型 | 必有 | 枚举 | 说明 |
|---|---|---:|---|---|
| `projectId` | `string` | 是 |  | 项目 ID |
| `status` | `string` | 是 | `pending/running/success` | 解析状态 |
| `updatedAt` | `string` | 是 | ISO 时间 | 更新时间 |
| `lastMessage` | `string` | 是 |  | 文案 |
| `canOperate` | `boolean` | 是 | `false` | 前端不可操作 |

---

## 4. Stages 阶段模块

## 4.1 `GET /projects/:id/stages`
功能：返回 S1-S10 阶段条目。

响应：`Stage[]`
| 字段 | 类型 | 必有 | 枚举/约束 | 说明 |
|---|---|---:|---|---|
| `id` | `number` | 是 | `1~10` | 阶段 ID |
| `name` | `string` | 是 |  | `Sx 名称` |
| `label` | `string` | 是 |  | 阶段短名 |
| `status` | `string` | 是 | `completed/active/pending` | 状态 |
| `isHuman` | `boolean` | 是 |  | 是否人工阶段（S3/S6） |

## 4.2 `PUT /projects/:id/stages/:stage`
功能：阶段推进（仅支持 `status=completed`）。

请求体：
| 字段 | 类型 | 必填 | 枚举 | 说明 |
|---|---|---:|---|---|
| `status` | `string` | 是 | `completed` | 阶段完成 |

成功响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `message` | `string` | 是 | 阶段推进结果 |
| `project` | `Project` | 是 | 最新项目对象 |
| `currentStage` | `number` | 是 | 推进后阶段 |

高频错误码：
- `STAGE_STATUS_NOT_SUPPORTED`
- `STAGE_LOCKED`
- `PARSE_NOT_COMPLETED`
- `DIRECTORY_NOT_COMPLETED`
- `GAP_RECOGNITION_NOT_COMPLETED`
- `GAP_REVIEW_NOT_SUBMITTED`
- `REVIEW_NOT_CONFIRMED`
- `FILL_NOT_COMPLETED`

---

## 5. S1-S10 业务阶段 API

## 5.1 S1 解析

### 5.1.1 `GET /projects/:id/parse-results`
响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `status` | `string` | 是 | `idle/completed` |
| `parsedAt` | `string` | 是 | 解析时间 |
| `tabs` | `string[]` | 是 | 解析标签 |
| `items` | `ParseItem[]` | 是 | 解析条目 |
| `sourceFiles` | `SourceFile[]` | 是 | 源文件信息 |
| `summary.fileCount` | `number` | 是 | 文件数 |
| `summary.totalPages` | `number` | 是 | 总页数 |
| `summary.extractedCount` | `number` | 是 | 提取条目数 |
| `summary.keyParamCount` | `number` | 是 | 关键参数数 |

`SourceFile`：`id/name/type/pageCount/size`。

`ParseItem` 常见字段：
`id/type/title/quote/keyEntity/keyValue/page/sourceFile/confidence/...`

### 5.1.2 `POST /projects/:id/parse-results/run`
功能：触发解析。

成功响应：`GET parse-results` 同结构 + `message`。

错误码：`PARSE_SOURCE_MISSING`

### 5.1.3 `POST /projects/:id/parse-results/upload-and-run`
功能：上传 S1 文件并自动解析（推荐使用）。

请求体：
| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `tenderFiles` | `FileMeta[]` | 是 | 招标文件列表（必选） |
| `templateFiles` | `FileMeta[]` | 否 | 模板文件列表（可选） |

`FileMeta`：`name/size/type`（`name` 必填，其余可选）。

成功响应：`GET parse-results` 同结构，额外包含：
- `project`（更新后的项目对象，含 `files/templateFiles`）
- `uploaded.tenderFiles`
- `uploaded.templateFiles`
- `message`

错误码：`PARSE_SOURCE_MISSING`

### 5.1.4 `PUT /projects/:id/parse-results/:rid`
功能：更新解析条目。

当前 mock 响应：`{ "message": "Updated" }`

## 5.2 S2 目录生成

### 5.2.1 `GET /projects/:id/directory-generation`
响应字段：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `status` | `string` | 是 | `idle/completed` |
| `percentage` | `number` | 是 | 完成度 |
| `summary` | `string` | 是 | 摘要 |
| `generatedAt` | `string` | 是 | 生成时间 |
| `output` | `object|null` | 是 | 输出文件 |
| `tasks` | `Task[]` | 是 | 内部处理步骤 |
| `source` | `object` | 是 | 项目来源信息 |

`output`（completed 时）：`fileName/fileType/fileUrl/sectionCount/chapterCount/outlineNodes`。

### 5.2.2 `POST /projects/:id/directory-generation/run`
成功响应：同上 + `message`。

错误码：`PARSE_NOT_COMPLETED`

## 5.3 S3 目录审核

### 5.3.1 `GET /projects/:id/outline`
响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `status` | `string` | 是 | 固定 `editable` |
| `nodes` | `OutlineNode[]` | 是 | 目录树 |
| `source.fromStage` | `string` | 是 | `S2` |
| `source.directoryFileName` | `string` | 是 | 目录文件名 |
| `summary.rootCount` | `number` | 是 | 根节点数 |
| `summary.totalNodeCount` | `number` | 是 | 总节点数 |
| `updatedAt` | `string` | 是 | 更新时间 |

`OutlineNode`：`id/title/children[]`。

### 5.3.2 `PUT /projects/:id/outline`
请求体：
| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `nodes` | `OutlineNode[]` | 是 | 编辑后的目录树 |

响应：同 `GET outline` + `message`。

### 5.3.3 `POST /projects/:id/outline/regenerate`
功能：按 S2 目录重生成 S3 审核稿。

错误码：`DIRECTORY_NOT_COMPLETED`

### 5.3.4 `POST /projects/:id/outline/confirm`
成功响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `message` | `string` | 是 | 确认提示 |
| `outline` | `object` | 是 | 当前目录数据 |

错误码：`OUTLINE_EMPTY`

## 5.4 S4 缺口识别

### 5.4.1 `GET /projects/:id/gaps-detection`
### 5.4.2 `POST /projects/:id/gaps-detection/run`
两者响应核心字段一致：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `status` | `string` | 是 | `idle/completed` |
| `recognizedAt` | `string` | 是 | 识别时间 |
| `summary.totalMissing` | `number` | 是 | 缺失项总数 |
| `summary.highPriorityCount` | `number` | 是 | 高优先级 |
| `summary.mediumPriorityCount` | `number` | 是 | 中优先级 |
| `summary.lowPriorityCount` | `number` | 是 | 低优先级 |
| `items` | `GapDetectItem[]` | 是 | 缺失项 |
| `source` | `object` | 是 | 来源信息 |

`GapDetectItem`：`id/section/title/desc/type/priority`。

## 5.5 S5 备料补交

### 5.5.1 `GET /projects/:id/gaps`
响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `status` | `string` | 是 | `idle/ready` |
| `recognizedAt` | `string` | 是 | 识别时间 |
| `submittedForReview` | `boolean` | 是 | 是否已提审 |
| `items` | `GapItem[]` | 是 | 缺口条目 |
| `submissions` | `Submission[]` | 是 | 提交回执 |

`GapItem`：
`id/section/title/desc/type/priority/bidType/status/resolvedSource/resolvedAt/skipReason/latestUploadAt/latestSubmissionId`

### 5.5.2 `POST /projects/:id/gaps/submit-review`
成功响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `message` | `string` | 是 | 提示文案 |
| `payload` | `GapFillingPayload` | 是 | 更新后的 S5 数据 |

错误码：`GAP_RECOGNITION_NOT_COMPLETED`、`GAPS_NOT_READY`

### 5.5.3 `PUT /projects/:id/gaps/:gid`
功能：更新单缺口状态（resolve/skip/checking）。

请求体：
| 字段 | 类型 | 必填 | 枚举 | 说明 |
|---|---|---:|---|---|
| `action` | `string` | 否 | `resolve/skip/checking` | 操作 |
| `status` | `string` | 否 | `resolved/skipped/checking` | 目标状态 |
| `reason` | `string` | 否 |  | skip 原因 |
| `source` | `string/object` | 否 |  | resolve 来源 |

响应：`message/item/payload`

### 5.5.4 `POST /projects/:id/gaps/:gid/upload`
功能：旧上传入口（兼容）。

响应：`message/item/payload`

### 5.5.5 `GET /projects/:id/materials/submissions`
响应：`items/total`

`Submission` 字段：
`receiptId/projectId/missingId/fileId/fileName/storedPath/action/operator/submittedAt/traceId/auditId`

### 5.5.6 `POST /projects/:id/materials/submissions`
功能：主补料接口（支持冲突覆盖/版本化）。

请求体：
| 字段 | 类型 | 必填 | 枚举/约束 | 说明 |
|---|---|---:|---|---|
| `missingId` | `string` | 是 |  | 缺口 ID |
| `bidType` | `string` | 否 | `技术标/商务标/通用` | 归档标书类型 |
| `targetPath` | `string` | 否 |  | 目标目录（可选） |
| `onConflict` | `string` | 否 | `overwrite/version` | 冲突策略 |
| `operator` | `string` | 否 |  | 操作者 |
| `files` | `FileMeta[]` | 是 | 单次≤5,单文件≤500MB,白名单扩展名 | 文件列表 |

`FileMeta`：`name/size/type`

成功响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `message` | `string` | 是 | 提交结果 |
| `item` | `GapItem` | 是 | 更新后的缺口项 |
| `receipts` | `Submission[]` | 是 | 回执列表 |
| `payload` | `GapFillingPayload` | 是 | 最新 S5 数据 |
| `traceId` | `string` | 是 | 跟踪 ID |

冲突错误（409）：`MATERIAL_CONFLICT`

### 5.5.7 `PATCH /projects/:id/materials/missing/:missingId`
功能：更新缺失项状态（常用于写入 skip 原因）。

请求体：
| 字段 | 类型 | 必填 | 枚举 | 说明 |
|---|---|---:|---|---|
| `status` | `string` | 是 | `skipped/resolved` | 状态 |
| `reason` | `string` | 否 |  | skipped 原因 |
| `resolvedSource` | `string` | 否 |  | resolved 来源 |

响应：`message/item/payload`

错误码：`GAP_NOT_FOUND`、`MISSING_STATUS_INVALID`

## 5.6 S6 审核备料

### 5.6.1 `GET /projects/:id/review-items`
`GET` 响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `status` | `string` | 是 | `idle/ready` |
| `confirmed` | `boolean` | 是 | 是否确认 |
| `reviewedAt` | `string` | 是 | 审核时间 |
| `summary.total/resolvedCount/skippedCount/pendingCount` | `number` | 是 | 统计 |
| `items` | `ReviewItem[]` | 是 | 审核条目 |
| `source` | `object` | 是 | 来源 |
| `parse.status` | `string` | 是 | `idle/completed` |
| `parse.parsedAt` | `string` | 是 | 解析时间 |
| `parse.fileName` | `string` | 是 | 解析文档名 |

`ReviewItem`：
`id/section/title/bidType/status/resolvedSource/skipReason/resolvedAt/priority/submission`

### 5.6.2 `POST /projects/:id/review-items/prepare`
功能：S5 提交后触发 S6 解析，生成可预览 Word 文档。

成功响应：`message + payload`，`payload` 结构同 `GET /projects/:id/review-items/document`。

### 5.6.3 `GET /projects/:id/review-items/document`
功能：获取 S6 OnlyOffice 预览会话。

响应字段：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `status` | `string` | 是 | `idle/ready` |
| `parseStatus` | `string` | 是 | `idle/completed` |
| `parsedAt` | `string` | 是 | 解析时间 |
| `documentId` | `string` | 是 | 文档 ID |
| `sourceFileName` | `string` | 是 | 来源文件名 |
| `fileName/fileType/fileUrl` | `string` | 是 | 预览文件信息 |
| `lastSavedAt/version` | `string/number` | 是 | 保存信息 |
| `onlyoffice` | `object` | 是 | `documentKey/title/fileUrl/callbackUrl/user` |
| `fallback.content` | `string` | 是 | 兜底文本内容 |

### 5.6.4 `PUT /projects/:id/review-items/document/save`
功能：S6 兜底文本保存回写。

请求体：`{ "content": "..." }`

### 5.6.5 `POST /projects/:id/review-items/document/force-save`
功能：S6 手动触发保存回写（OnlyOffice 预留）。

### 5.6.6 `POST /projects/:id/review-items/document/callback`
功能：S6 OnlyOffice 回调入口（预留）。

### 5.6.7 `POST /projects/:id/review-items/confirm`
功能：S6 审核确认并允许进入 S7。

`confirm` 成功响应：`message/payload`。

错误码：`GAP_REVIEW_NOT_SUBMITTED`、`REVIEW_ITEMS_NOT_READY`

## 5.7 S7 正文拼装

### 5.7.1 `GET /projects/:id/fill-generation`
### 5.7.2 `POST /projects/:id/fill-generation/run`
响应字段：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `status` | `string` | 是 | `idle/completed` |
| `filledAt` | `string` | 是 | 完成时间 |
| `runDurationSec` | `number` | 是 | 秒数 |
| `runDuration` | `string` | 是 | 文案时长 |
| `output.fileName` | `string` | 否 | 输出文件名 |
| `output.fileType` | `string` | 否 | `docx` |
| `output.size` | `string` | 否 | 文件大小 |
| `output.fileUrl` | `string` | 否 | 下载地址 |
| `summary` | `string` | 是 | 摘要 |
| `source` | `object` | 是 | 来源 |
| `coverage` | `object` | 否 | S8 素材拼装覆盖摘要 |
| `assembly` | `object` | 否 | S7 拼装工作目录、manifest、报告路径 |

`run` 额外返回 `message`。当前接口名仍为 `fill-generation`，实际语义是按 S2 目录 JSON、Wiki 卡片和素材库清洗后 Word 拼装技术标正文。

错误码：`REVIEW_NOT_CONFIRMED`

## 5.8 S8 素材拼装覆盖校验

### 5.8.1 `GET /projects/:id/coverage`
响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `percentage` | `number` | 是 | 全局覆盖率 |
| `fullCover` | `number` | 是 | 完全覆盖数 |
| `partialCover` | `number` | 是 | 部分覆盖数 |
| `noCover` | `number` | 是 | 未覆盖数 |
| `tree` | `CoverageNode[]` | 是 | 按素材 `scope/category` 分组的拼装覆盖树 |
| `partialItems` | `CoverageIssue[]` | 是 | 未匹配目录项或需人工确认项 |
| `noCoverItems` | `CoverageIssue[]` | 是 | 素材库中未拼装的素材清单 |

`CoverageNode`：
- 父节点：`id/title/coverage/children[]`
- 叶节点：`id/title/status( full/partial/none )/coverage`

`CoverageIssue`：`id/title/nodeTitle/status`

## 5.9 S9 人机共创

### 5.9.1 `GET /projects/:id/document`
响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `status` | `string` | 是 | `ready` |
| `documentId` | `string` | 是 | 文档 ID |
| `sourceFileName` | `string` | 是 | 来源文件名 |
| `sourceFileUrl` | `string` | 是 | 来源文件 URL |
| `fileName` | `string` | 是 | 当前编辑文件名 |
| `fileType` | `string` | 是 | 文件类型 |
| `fileUrl` | `string` | 是 | 当前文件 URL |
| `lastSavedAt` | `string` | 是 | 最近保存 |
| `version` | `number` | 是 | 版本号 |
| `onlyoffice` | `object` | 是 | OnlyOffice 会话 |
| `fallback.content` | `string` | 是 | 兜底编辑内容 |

`onlyoffice` 子字段：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `documentKey` | `string` | 是 | 文档 key |
| `title` | `string` | 是 | 编辑器标题 |
| `fileUrl` | `string` | 是 | 文档 URL |
| `callbackUrl` | `string` | 是 | 回调地址 |
| `user.id/name` | `string` | 是 | 编辑用户 |

### 5.9.2 `PUT /projects/:id/document/save`
请求体：
| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `content` | `string` | 是 | 兜底编辑内容 |

成功响应：`message/payload`，其中 `payload` 为 `GET /document` 同结构。

错误码：`DOCUMENT_CONTENT_REQUIRED`

### 5.9.3 `POST /projects/:id/document/force-save`
功能：触发版本+1并回写。

成功响应：`message/payload`

### 5.9.4 `POST /projects/:id/document/callback`
功能：OnlyOffice 回调。

请求体常用字段：
| 字段 | 类型 | 必填 | 枚举/约束 | 说明 |
|---|---|---:|---|---|
| `status` | `number` | 是 | `2/6/7` 视为可保存 | 回调状态 |
| `url` | `string` | 否 |  | 编辑后文件地址 |

响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `error` | `number` | 是 | `0` 成功，`1` 项目不存在 |

## 5.10 S10 导出

### 5.10.1 `GET /projects/:id/final-document`
响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `ready` | `boolean` | 是 | 是否可下载 |
| `fileName` | `string` | 是 | 文件名 |
| `fileType` | `string` | 是 | 文件类型 |
| `fileUrl` | `string` | 是 | 下载地址 |
| `lastSavedAt` | `string` | 是 | 最近保存 |
| `version` | `number` | 是 | 版本 |

### 5.10.2 `GET /projects/:id/export/check`
响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `checks` | `CheckItem[]` | 是 | 校验项 |
| `warnings` | `WarningItem[]` | 是 | 警告项 |
| `requiresWarningConfirm` | `boolean` | 是 | 是否必须确认警告 |
| `suggestedFileName` | `string` | 是 | 建议导出名 |

`CheckItem`：`label/passed/code`

### 5.10.3 `POST /projects/:id/export`
请求体：
| 字段 | 类型 | 必填 | 枚举/约束 | 说明 |
|---|---|---:|---|---|
| `fileName` | `string` | 是 | 仅允许 `[A-Za-z0-9_\u4e00-\u9fa5-]` | 导出文件名（不含后缀） |
| `format` | `string` | 是 | `docx/pdf` | 导出格式 |
| `warningConfirmed` | `boolean` | 是 | `true` 才允许 | 警告确认 |

成功响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `message` | `string` | 是 | `Exported` |
| `fileUrl` | `string` | 是 | 下载地址 |
| `fileName` | `string` | 是 | 带后缀文件名 |
| `project` | `Project` | 是 | 导出后项目状态 |

错误码：
- `EXPORT_BLOCKED_BY_COVERAGE`
- `EXPORT_NAME_REQUIRED`
- `EXPORT_NAME_INVALID`
- `EXPORT_WARNING_NOT_CONFIRMED`
- `EXPORT_FORMAT_INVALID`

---

## 6. Materials Raw 原始素材库

## 6.1 `GET /materials/raw/permissions`
Query/Header：`role` 或 `x-user-role`。

响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `role` | `string` | 是 | `admin/member` |
| `rules[]` | `object[]` | 是 | 路径权限规则 |
| `rules[].pathPrefix` | `string` | 是 | 路径前缀 |
| `rules[].actions` | `object` | 是 | `upload/rename/move/delete` 布尔值 |

## 6.2 `GET /materials/raw/tree`
响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `tree` | `FolderNode[]` | 是 | 目录树 |
| `updatedAt` | `string` | 是 | 更新时间 |

`FolderNode`：`id/name/path/fileCount/children[]`

## 6.3 `GET /materials/raw/files`
Query：`folderPath/projectId/customerName/bidType/keyword/page/pageSize`

响应：`items/total/page/pageSize`

`RawFile` 关键字段：
`id/name/ext/type/size/sizeLabel/folderPath/projectId/customerName/bidType/version/updatedAt/lastAction/lastOperator`

## 6.4 `POST /materials/raw/folders/bootstrap`
请求体：`projectId`（必填）

成功响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `message` | `string` | 是 | 初始化提示 |
| `payload` | `object` | 是 | 同 `projects/:id/materials-path` |

错误码：`PROJECT_ID_REQUIRED`、`PROJECT_NOT_FOUND`

## 6.5 `POST /materials/raw/folders`
请求体：
| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `folderName/name` | `string` | 是 | 新文件夹名 |
| `parentPath` | `string` | 否 | 父路径 |
| `operator` | `string` | 否 | 操作者 |

响应：`message/folderPath/tree/traceId/auditId`

错误码：`RAW_FOLDER_NAME_REQUIRED`、`RAW_FOLDER_EXISTS`

## 6.6 `DELETE /materials/raw/folders`
参数：`path`（Query 或 Body）

成功响应：`message/folderPath/tree/traceId/auditId`

错误码：
- `RAW_FOLDER_PATH_REQUIRED`
- `RAW_FOLDER_NOT_FOUND`
- `RAW_FOLDER_PROTECTED`
- `RAW_FOLDER_NOT_CUSTOM`
- `RAW_FOLDER_NOT_EMPTY`
- `RAW_FOLDER_HAS_CHILDREN`

## 6.7 `POST /materials/raw/upload`
请求体：
| 字段 | 类型 | 必填 | 枚举/约束 | 说明 |
|---|---|---:|---|---|
| `files` | `FileMeta[]` | 是 | 单次≤5，单文件≤500MB | 文件列表 |
| `projectId` | `string` | 否 |  | 项目 ID |
| `bidType` | `string` | 否 | `技术标/商务标/通用` | 标书类型 |
| `targetPath` | `string` | 否 |  | 目标路径 |
| `onConflict` | `string` | 否 | `overwrite/version` | 冲突策略 |
| `operator` | `string` | 否 |  | 操作者 |
| `customerName` | `string` | 否 |  | 客户名（非项目场景） |

成功响应：`message/items/traceId`

冲突错误：`MATERIAL_CONFLICT`

## 6.8 `PATCH /materials/raw/:fileId`
功能：重命名。

请求体：`name`（必填）、`operator`（可选）

成功响应：`message/item/traceId`

错误码：`RAW_FILE_NOT_FOUND`、`RAW_FILE_NAME_REQUIRED`、`MATERIAL_CONFLICT`

## 6.9 `POST /materials/raw/move`
请求体：
| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `fileId` | `string` | 是 | 文件 ID |
| `targetPath` | `string` | 是 | 目标路径 |
| `onConflict` | `string` | 否 | `overwrite/version` |
| `operator` | `string` | 否 | 操作者 |

成功响应：`message/item/traceId`

错误码：`RAW_MOVE_INVALID`、`RAW_FILE_NOT_FOUND`、`MATERIAL_CONFLICT`

## 6.10 `DELETE /materials/raw/:fileId`
成功响应：`message/item/traceId`

错误码：`RAW_FILE_NOT_FOUND`

## 6.11 `GET /materials/raw/:fileId/download`
成功响应：`fileId/fileName/downloadUrl/message`

错误码：`RAW_FILE_NOT_FOUND`

## 6.12 `GET /audit/material-actions`
Query：`projectId/operator/folderPath/start/end`

响应：`items/total`

`MaterialAction` 字段：
`id/action/operator/fileId/fileName/folderPath/timestamp/traceId`

---

## 7. Materials Structured 结构化素材库

## 7.1 `GET /materials/structured`
Query：`table`（`all/turbine_models/project_performance/personnel`）

响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `categories` | `string[]` | 是 | 分类文案 |
| `tables` | `TableMeta[]` | 是 | 数据表元信息 |
| `currentTable` | `string` | 是 | 当前表 |
| `items` | `StructuredItem[]` | 是 | 条目 |
| `importHistory` | `ImportHistory[]` | 是 | 导入历史 |
| `latestReceipt` | `ImportReceipt|null` | 是 | 最新回执 |
| `total` | `number` | 是 | 条目总数 |

`StructuredItem`：`id/name/type/tableKey/version/updatedAt/icon/row?`

## 7.2 `GET /materials/structured/template`
Query：`table`

响应关键字段：
`table/fileName/templateVersion/requiredFields/optionalFields/templateColumns/sampleRows/notes`

## 7.3 `POST /materials/structured/import/preview`
请求体常用字段：
`table/fileName/fileSize/detectedColumns/mapping/previewRows`

响应关键字段：
`table/file/detectedColumns/fields/suggestedMapping/mapping/previewRows/summary/errors/canImport/snapshotHint`

## 7.4 `POST /materials/structured/import/confirm`
请求体同预检。

成功响应：
`message/receipt/historyItem`

`receipt` 字段：
`importId/snapshotId/table/fileName/totalRows/successCount/failCount/version/operator/importedAt/errors`

错误码：`MATERIAL_IMPORT_VALIDATION_FAILED`、`MATERIAL_IMPORT_EMPTY`

## 7.5 `POST /materials/structured`
功能：新增条目（简化 mock）。

响应：`{ id, ...req.body }`

## 7.6 `PUT /materials/structured/:id`
响应：`{ "message": "Updated" }`

## 7.7 `DELETE /materials/structured/:id`
响应：`{ "message": "Deleted" }`

## 7.8 `POST /materials/structured/import`
响应：`{ "imported": 12, "failed": 0 }`

---

## 8. Materials Wiki 知识素材库

## 8.1 `GET /materials/wiki`
Query：`nodeId`（可选）

响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `tree` | `WikiTreeNode[]` | 是 | 树（含 selected） |
| `selectedNode` | `WikiNodeDetail|null` | 是 | 选中节点详情 |
| `tagOptions` | `string[]` | 是 | 标签选项 |
| `applicableTypeOptions` | `string[]` | 是 | 适用类型选项 |

`WikiNodeDetail`：
`id/title/markdownContent/aiSummary/tags/applicableTypes/attachments/path/pathText/isFolder`

`Attachment`：`id/name/size/time/downloadUrl`

## 8.2 `POST /materials/wiki`
请求体：
| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `parentId` | `string` | 否 | 父节点 ID |
| `title` | `string` | 否 | 标题（默认“新建节点”） |
| `isFolder` | `boolean` | 否 | 是否目录 |
| `tags` | `string[]` | 否 | 初始标签 |
| `applicableTypes` | `string[]` | 否 | 适用类型 |

成功响应：`message + wiki payload`

## 8.3 `PUT /materials/wiki/:id`
请求体：
`title/markdownContent/aiSummary/tags/applicableTypes`

成功响应：`message + wiki payload`

错误码：`WIKI_NODE_NOT_FOUND`

## 8.4 `POST /materials/wiki/:id/move`
请求体：
| 字段 | 类型 | 必填 | 枚举 | 说明 |
|---|---|---:|---|---|
| `targetId` | `string` | 是 |  | 目标节点 ID |
| `mode` | `string` | 否 | `inside/before` | 移动模式 |

成功响应：`message + wiki payload`

错误码：
- `WIKI_MOVE_TARGET_REQUIRED`
- `WIKI_MOVE_SELF`
- `WIKI_NODE_NOT_FOUND`
- `WIKI_MOVE_DESCENDANT`
- `WIKI_MOVE_TARGET_NOT_FOUND`

## 8.5 `POST /materials/wiki/:id/attachments`
请求体：`fileName`（必填）、`fileSize`（可选）

成功响应：`message/attachment + wiki payload`

错误码：`WIKI_NODE_NOT_FOUND`、`WIKI_ATTACHMENT_NAME_REQUIRED`

## 8.6 `POST /materials/wiki/:id/refresh-summary`
成功响应：`summary + wiki payload`

错误码：`WIKI_NODE_NOT_FOUND`

---

## 9. Audit 审计模块

## 9.1 `GET /audit`
Query：`user/module/action/status/keyword/startDate/endDate`

响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `items` | `AuditItem[]` | 是 | 日志列表 |
| `total` | `number` | 是 | 总数 |
| `page` | `number` | 是 | 当前页（mock 固定1） |
| `pageSize` | `number` | 是 | 每页（mock 固定20） |
| `filterOptions` | `object` | 是 | 可选过滤项 |

`AuditItem`：
`id/time/user/userAvatar/action/actionType/module/moduleLabel/target/status/diff`

`diff`：`before/after` 任意对象。

## 9.2 `GET /audit/export`
Query 同 `GET /audit`

响应：`fileName/items`

## 9.3 `GET /audit/:id`
响应：`AuditItem + summary`

错误码：`AUDIT_NOT_FOUND`

---

## 10. Settings 设置中心

## 10.1 用户与角色

### 10.1.1 `GET /settings/users`
响应：`items/total`

`User` 字段：`id/name/email/avatar/dept/roles/status`

### 10.1.2 `POST /settings/users`
请求体：自由对象（建议同 User 结构）。

响应：`{ id: "U-...", ...req.body }`

### 10.1.3 `PUT /settings/users/:id`
响应：`{ "message": "Updated" }`

## 10.2 LLM 网关

### 10.2.1 `GET /settings/llm-gateway`
响应字段：
`enabled/endpoint/model/timeoutMs/maxTokens/apiKeyMasked/updatedAt/updatedBy`

### 10.2.2 `PUT /settings/llm-gateway`
请求体（可部分更新）：
`enabled/endpoint/model/timeoutMs/maxTokens`

响应：`message/config`

### 10.2.3 `POST /settings/llm-gateway/test`
请求体：`endpoint/model`（均必填）

成功响应：`success/latencyMs/message`

错误码：`GATEWAY_TEST_INVALID`

## 10.3 dotx 模板

### 10.3.1 `GET /settings/dotx-templates`
响应：`items`

`DotxItem`：`id/name/version/uploadedBy/uploadedAt/size/isActive`

### 10.3.2 `POST /settings/dotx-templates`
请求体：`fileName`（必填）、`version`（可选）、`fileSize`（可选）

响应：`message/item/items`

错误码：`DOTX_NAME_REQUIRED`

### 10.3.3 `POST /settings/dotx-templates/:id/activate`
响应：`message/item/items`

错误码：`DOTX_NOT_FOUND`

## 10.4 Excel 模板版本

### 10.4.1 `GET /settings/excel-templates`
响应：
- `items`（模板版本）
- `tableOptions`（可绑定数据表）

`ExcelTemplateItem`：
`id/tableKey/tableLabel/version/uploadedBy/uploadedAt/fileName/isActive`

### 10.4.2 `POST /settings/excel-templates`
请求体：`tableKey`（必填）、`fileName`（必填）、`version`（可选）

响应：`message/item/items`

错误码：`XLSX_TABLE_INVALID`、`XLSX_NAME_REQUIRED`

### 10.4.3 `POST /settings/excel-templates/:id/activate`
响应：`message/item/items`

错误码：`XLSX_TEMPLATE_NOT_FOUND`

## 10.5 备份与恢复

### 10.5.1 `GET /settings/backups`
响应：
| 字段 | 类型 | 必有 | 说明 |
|---|---|---:|---|
| `items` | `BackupItem[]` | 是 | 备份记录 |
| `latestRestoreAt` | `string|null` | 是 | 最近恢复时间 |

`BackupItem`：
`id/type/status/size/createdAt/createdBy/note/restoredAt?/restoredBy?`

### 10.5.2 `POST /settings/backups/create`
请求体：`note`（可选）

响应：`message/item/items`

### 10.5.3 `POST /settings/backups/:id/restore`
响应：`message/item/items`

错误码：`BACKUP_NOT_FOUND`

## 10.6 系统健康

### 10.6.1 `GET /settings/health`
响应：`HealthItem[]`

`HealthItem` 常见字段：
`name/status/latency/message/updatedAt`

---

## 11. 常用错误码索引（按模块）

| 模块 | 代表错误码 |
|---|---|
| Auth | `EMAIL_REQUIRED` / `PASSWORD_REQUIRED` / `AUTH_INVALID_CREDENTIALS` / `AUTH_UNAUTHORIZED` / `AUTH_TOKEN_INVALID` |
| 项目 | `PROJECT_NOT_FOUND` / `STAGE_UPDATE_FORBIDDEN` |
| 阶段门禁 | `STAGE_LOCKED` / `PARSE_NOT_COMPLETED` / `DIRECTORY_NOT_COMPLETED` / `GAP_RECOGNITION_NOT_COMPLETED` / `GAP_REVIEW_NOT_SUBMITTED` / `REVIEW_NOT_CONFIRMED` / `FILL_NOT_COMPLETED` |
| S5补料 | `GAPS_NOT_READY` / `GAP_NOT_FOUND` / `MISSING_STATUS_INVALID` / `MATERIAL_CONFLICT` / `RAW_TARGET_PATH_REQUIRED` |
| S9/S10 | `DOCUMENT_CONTENT_REQUIRED` / `EXPORT_BLOCKED_BY_COVERAGE` / `EXPORT_NAME_REQUIRED` / `EXPORT_NAME_INVALID` / `EXPORT_WARNING_NOT_CONFIRMED` / `EXPORT_FORMAT_INVALID` |
| Raw 素材 | `RAW_FILE_NOT_FOUND` / `RAW_FILE_NAME_REQUIRED` / `RAW_FOLDER_*` / `RAW_MOVE_INVALID` |
| Structured | `MATERIAL_IMPORT_VALIDATION_FAILED` / `MATERIAL_IMPORT_EMPTY` |
| Wiki | `WIKI_NODE_NOT_FOUND` / `WIKI_MOVE_*` / `WIKI_ATTACHMENT_NAME_REQUIRED` |
| 审计 | `AUDIT_NOT_FOUND` |
| 设置 | `GATEWAY_TEST_INVALID` / `DOTX_*` / `XLSX_*` / `BACKUP_NOT_FOUND` |

---

## 12. 与前端 API 封装的映射关系

`src/api/index.js` 已全部覆盖上述接口，建议联调时按以下命名对照：
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
