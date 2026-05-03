# MVP接口与参数核心版

> 用途：当前 `Web -> FastAPI` 的正式开发基线
> 原则：保留现有前端接口名，FastAPI 统一承接 `/api`
> 更新日期：2026-05-03

## 1. 当前 MVP 口径

- 主流程统一为 `S0-S6`
- `S0` 是全局解析/审核模块：上传招标文件、结构化解析、投标决策和项目信息补全
- 项目模块阶段条只展示 `S1-S6`
- 当前阶段：`S1 模板与目录 / S2 审核目录 / S3 缺口处理 / S4 生成标书 / S5 共创 / S6 导出`
- `fill-generation`、`coverage` 等接口名是历史兼容名，不代表旧独立阶段
- 项目内历史 URL `/projects/:id/parse` 兼容跳转到 `/projects/:id/template-directory`
- `S0` 上传必须是真文件上传：`multipart/form-data`，不能只传文件名或文件元数据

## 2. 项目与阶段

### 2.1 项目列表

#### `GET /api/projects`

返回最少字段：

```json
[
  {
    "id": "PRJ-001",
    "name": "甘肃华能100MW风电项目",
    "customerName": "华能集团",
    "manager": "张建国",
    "deadline": "2026-05-01",
    "bidType": "技术标",
    "currentStage": 1,
    "stageLabel": "模板与目录",
    "updatedAt": "2026-04-19T10:00:00.000Z"
  }
]
```

### 2.2 创建项目

#### `POST /api/projects`

请求：

```json
{
  "name": "甘肃华能100MW风电项目",
  "customerName": "华能集团",
  "manager": "张建国",
  "deadline": "2026-05-01",
  "bidType": "技术标",
  "owner": "华能集团",
  "isKeyAccount": true,
  "keyAccountId": "KA-HN"
}
```

返回最少字段：

```json
{
  "id": "PRJ-001",
  "name": "甘肃华能100MW风电项目",
  "customerName": "华能集团",
  "manager": "张建国",
  "deadline": "2026-05-01",
  "bidType": "技术标",
  "files": [],
  "templateFiles": [],
  "currentStage": 1,
  "stageLabel": "模板与目录"
}
```

### 2.3 获取项目详情

#### `GET /api/projects/{id}`

返回最少字段：

```json
{
  "id": "PRJ-001",
  "name": "甘肃华能100MW风电项目",
  "customerName": "华能集团",
  "manager": "张建国",
  "deadline": "2026-05-01",
  "bidType": "技术标",
  "files": ["招标文件.pdf"],
  "templateFiles": [
    {
      "id": "TPL-1",
      "name": "技术标模板.docx",
      "sizeLabel": "2.1 MB"
    }
  ],
  "currentStage": 1,
  "stageLabel": "模板与目录"
}
```

### 2.4 阶段条

#### `GET /api/projects/{id}/stages`

返回最少字段：

```json
[
  { "id": 1, "name": "模板与目录", "status": "active", "isHuman": false, "routeStageId": 1 },
  { "id": 2, "name": "审核目录", "status": "pending", "isHuman": true, "routeStageId": 2 },
  { "id": 3, "name": "缺口处理", "status": "pending", "isHuman": true, "routeStageId": 3 },
  { "id": 4, "name": "生成标书", "status": "pending", "isHuman": false, "routeStageId": 4 },
  { "id": 5, "name": "共创", "status": "pending", "isHuman": true, "routeStageId": 5 },
  { "id": 6, "name": "导出", "status": "pending", "isHuman": false, "routeStageId": 6 }
]
```

#### `PUT /api/projects/{id}/stages/{stage}`

请求：

```json
{
  "status": "completed"
}
```

返回最少字段：

```json
{
  "message": "阶段状态已更新",
  "currentStage": 2,
  "stageLabel": "审核目录"
}
```

说明：

- 推荐传当前 `1-6` 阶段号。
- 旧客户端传 `7/8/9/10` 时，后端会兼容映射到当前 `S4/S4/S5/S6`。

## 3. S0 解析

### 3.1 上传并解析

#### `POST /api/projects/{id}/parse-results/upload-and-run`

请求：

- `multipart/form-data`
- `tenderFiles[]`: 招标文件，必选，可多份
- `templateFiles[]`: 项目模板文件，可选

返回最少字段：

```json
{
  "status": "completed",
  "parsedAt": "2026-04-19T10:30:00.000Z",
  "message": "上传成功，已自动解析 1 份招标文件。",
  "project": {
    "id": "PRJ-001",
    "files": ["招标文件.pdf"],
    "templateFiles": [],
    "currentStage": 1,
    "stageLabel": "模板与目录"
  },
  "sourceFiles": [
    {
      "id": "SRC-1",
      "name": "招标文件.pdf",
      "type": "PDF",
      "pageCount": 128,
      "size": "18.4 MB"
    }
  ],
  "items": [
    {
      "id": "ITEM-1",
      "type": "技术参数",
      "title": "叶轮直径",
      "keyEntity": "叶轮直径",
      "keyValue": "220m",
      "page": 12,
      "sourceFile": "招标文件.pdf"
    }
  ],
  "summary": {
    "fileCount": 1,
    "extractedCount": 18
  }
}
```

### 3.2 获取解析结果

#### `GET /api/projects/{id}/parse-results`

返回最少字段：

```json
{
  "status": "completed",
  "parsedAt": "2026-04-19T10:30:00.000Z",
  "sourceFiles": [],
  "items": [],
  "summary": {
    "fileCount": 1,
    "extractedCount": 18
  }
}
```

## 4. S1 模板与目录

### 4.1 获取有效模板来源

#### `GET /api/projects/{id}/template-fallback`

返回最少字段：

```json
{
  "enabled": true,
  "source": "system-default",
  "template": {
    "available": true,
    "name": "投标文件-模板.docx",
    "minioBucket": "bid-templates",
    "minioKey": "templates/default/technical/xxx-投标文件-模板.docx"
  }
}
```

### 4.2 上传项目模板

#### `POST /api/projects/{id}/template-files/upload`

请求：

- `multipart/form-data`
- `templateFiles[]`: 项目模板文件

说明：

- 项目上传模板优先。
- 项目没有上传模板时才读取设置侧系统默认模板。
- 设置侧系统默认模板不会混入项目上传模板列表。

### 4.3 获取目录生成状态

#### `GET /api/projects/{id}/directory-generation`

返回最少字段：

```json
{
  "status": "idle",
  "percentage": 0,
  "summary": "尚未生成目录。",
  "generatedAt": "",
  "output": null,
  "tasks": [
    { "id": "task-1", "label": "解析章节线索", "status": "pending" },
    { "id": "task-2", "label": "调用目录生成 skill", "status": "pending" },
    { "id": "task-3", "label": "保存目录结果", "status": "pending" }
  ]
}
```

### 4.4 生成目录

#### `POST /api/projects/{id}/directory-generation/run`

请求：

```json
{
  "outlineStrategy": "strict",
  "includeKeyPoints": true
}
```

返回最少字段：

```json
{
  "status": "completed",
  "percentage": 100,
  "summary": "目录生成完成。",
  "generatedAt": "2026-04-19T10:40:00.000Z",
  "output": {
    "fileName": "甘肃华能100MW风电项目_目录.docx",
    "fileType": "docx",
    "chapterCount": 12
  },
  "message": "目录生成完成"
}
```

说明：

- 命令名仍为 `s2toc`，工作区仍为 `s2_toc_workdir`，这是历史内部名。
- 业务阶段是当前 `S1 模板与目录`。

## 5. S2 审核目录

### 5.1 获取目录审核稿

#### `GET /api/projects/{id}/outline`

返回最少字段：

```json
{
  "outlineVersion": 1,
  "reviewStatus": "draft",
  "generatedAt": "2026-04-19T10:40:00.000Z",
  "summary": {
    "totalNodeCount": 12
  },
  "nodes": [
    {
      "id": "OL-1",
      "title": "项目概况",
      "children": []
    }
  ]
}
```

### 5.2 保存目录审核稿

#### `PUT /api/projects/{id}/outline`

请求：

```json
{
  "nodes": [],
  "comment": "已确认目录结构"
}
```

### 5.3 重生成目录审核稿

#### `POST /api/projects/{id}/outline/regenerate`

### 5.4 确认目录

#### `POST /api/projects/{id}/outline/confirm`

返回最少字段：

```json
{
  "message": "目录已确认",
  "outlineVersion": 3,
  "reviewStatus": "confirmed"
}
```

## 6. S3 缺口处理

### `GET /api/projects/{id}/gaps-detection`

获取缺口识别状态和处理计划。

### `POST /api/projects/{id}/gaps-detection/run`

调用缺口识别 Skill，生成匹配/缺口/处理计划。

### `GET /api/projects/{id}/gaps`

获取统一缺口处理页数据。

### `PUT /api/projects/{id}/gaps/{gap_id}`

更新缺口项处理动作或人工说明。

### `POST /api/projects/{id}/gaps/{gap_id}/upload`

上传客户资料并挂回缺口计划。

### `POST /api/projects/{id}/gaps/{gap_id}/select-material`

选择素材库已有素材并挂回缺口计划。

### `POST /api/projects/{id}/gaps/{gap_id}/ai-fill`

调用 AI 填写 Skill，按人工指定的空表/Word 和参考素材补齐缺口。

### `POST /api/projects/{id}/gaps/recheck`

重新检查缺口完整性。

### `POST /api/projects/{id}/review-items/confirm`

确认缺口处理结果，允许进入标书生成。

## 7. S4 生成标书

### 7.1 获取拼装状态

#### `GET /api/projects/{id}/fill-generation`

返回最少字段：

```json
{
  "status": "idle",
  "filledAt": "",
  "runDurationSec": 0,
  "runDuration": "",
  "summary": "尚未生成标书，请点击“生成标书”后继续。",
  "output": null
}
```

### 7.2 触发正文拼装

#### `POST /api/projects/{id}/fill-generation/run`

请求：

```json
{
  "allowPlaceholder": true,
  "traceEvidence": true
}
```

返回最少字段：

```json
{
  "status": "completed",
  "filledAt": "2026-04-19T11:00:00.000Z",
  "summary": "技术标正文拼装完成。",
  "output": {
    "fileName": "甘肃华能100MW风电项目_正文.docx",
    "fileType": "docx",
    "size": "2.8 MB",
    "fileUrl": "/files/DOC-001.docx"
  },
  "coverage": {
    "percentage": 80,
    "fullCover": 4,
    "partialCover": 1,
    "noCover": 1
  },
  "assembly": {
    "skill": "bid-tech-assembler",
    "manifestPath": "/data/documents/PRJ-001/technical-workspace/s7_assembly_workdir/s7_assembly_input.json",
    "assemblyReport": "/data/documents/PRJ-001/technical-workspace/s7_assembly_workdir/assembly_report.md",
    "needsReview": "/data/documents/PRJ-001/technical-workspace/s7_assembly_workdir/needs_review.md"
  },
  "message": "正文拼装完成"
}
```

说明：

- 当前 `S4` 会读取 `S1` 目录 JSON、Wiki 卡片、素材库清洗后 Word、`S3` 缺口计划和补料/AI 填写产物。
- 历史内部工作区仍叫 `s7_assembly_workdir`。
- 输出 Word 会写入项目文档路径，`S5/S6` 继续读取该文件。

### 7.3 覆盖诊断

#### `GET /api/projects/{id}/coverage`

返回正文拼装计划对应的素材覆盖诊断。它是诊断能力，不是独立主流程阶段。

## 8. S5 文档共创

### 8.1 获取编辑文档

#### `GET /api/projects/{id}/document`

返回最少字段：

```json
{
  "status": "ready",
  "documentId": "DOC-001",
  "sourceFileName": "甘肃华能100MW风电项目_正文.docx",
  "fileName": "甘肃华能100MW风电项目_正文.docx",
  "fileType": "docx",
  "lastSavedAt": "2026-04-19T11:10:00.000Z",
  "version": 1,
  "onlyoffice": {
    "documentKey": "PRJ-001-v1",
    "title": "甘肃华能100MW风电项目_正文.docx",
    "fileUrl": "http://127.0.0.1:8000/files/DOC-001.docx",
    "callbackUrl": "http://127.0.0.1:8000/api/projects/PRJ-001/document/callback",
    "user": {
      "id": "user-1",
      "name": "当前用户"
    }
  }
}
```

说明：

- 这里不用旧口径 `editorSession`。
- 当前前端共创页面直接读取顶层 `onlyoffice`。

### 8.2 保存回写兜底内容

#### `PUT /api/projects/{id}/document/save`

### 8.3 强制回写

#### `POST /api/projects/{id}/document/force-save`

### 8.4 OnlyOffice 回调

#### `POST /api/projects/{id}/document/callback`

## 9. S6 最终下载

### `GET /api/projects/{id}/final-document`

返回最少字段：

```json
{
  "ready": true,
  "fileName": "甘肃华能100MW风电项目_终稿.docx",
  "fileType": "docx",
  "fileUrl": "http://127.0.0.1:8000/files/DOC-001-final.docx",
  "lastSavedAt": "2026-04-19T11:22:00.000Z",
  "version": 3
}
```

### `GET /api/projects/{id}/export/check`

导出前检查。当前是 MVP 轻量真实，评分点级审计仍待升级。

### `POST /api/projects/{id}/export`

导出动作。当前 MVP 仅支持 DOCX。

## 10. 只记这几个核心对象

### `Project`

- `id`
- `name`
- `customerName`
- `manager`
- `deadline`
- `bidType`
- `files`
- `templateFiles`
- `currentStage`
- `stageLabel`

### `Stage`

- `id`
- `name`
- `status`
- `isHuman`
- `routeStageId`

### `ParseResult`

- `status`
- `parsedAt`
- `sourceFiles`
- `items`
- `summary`

### `OutlineNode`

- `id`
- `title`
- `children`

### `GapPlan`

- `tocItemId`
- `status`
- `matchedMaterials`
- `requiredInputs`
- `fillTasks`
- `resolvedArtifacts`

### `DocumentWorkspace`

- `documentId`
- `fileName`
- `fileUrl`
- `version`
- `onlyoffice`
- `fallback`

## 11. 开发时最重要的 4 句话

1. FastAPI 统一承接所有 `/api`，前端不再直接连 mock-server。
2. `S0` 必须上传真实文件，不是只传文件名或文件元数据。
3. `S1` 负责生成目录 JSON，`S3` 负责补齐缺口，`S4` 负责按目录和缺口计划从素材库拼装正文。
4. `S5` 按当前前端的 `onlyoffice` 字段结构实现，不走旧 `editorSession` 口径。
