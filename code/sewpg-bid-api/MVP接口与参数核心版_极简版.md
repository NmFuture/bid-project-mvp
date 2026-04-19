# MVP接口与参数核心版

> 用途：当前 `Web -> FastAPI` 的正式开发基线  
> 原则：保留现有前端接口名，FastAPI 统一承接 `/api`

---

## 1. 当前 MVP 口径

- 前端展示流保留 `S0-S10`
- 当前真实实现：`S0 / S1 / S2 / S3 / S7 / S9 / S10`
- 当前 mock：`S4 / S5 / S6 / S8`
- 当前 `S7` 页面承担“初稿生成”，这是 MVP 借现有页面做最小改动，不代表正式版最终 `S7` 语义
- `S2` 和 `S7` 后续都要接 `opencode skill`
- `S9` 走 `OnlyOffice`
- `S1` 上传必须是真文件上传：`multipart/form-data`，不能只传文件名或文件元数据

---

## 2. 项目与阶段

## 2.1 项目列表

### `GET /api/projects`

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
    "stageLabel": "S1 解析",
    "updatedAt": "2026-04-19T10:00:00.000Z"
  }
]
```

## 2.2 创建项目

### `POST /api/projects`

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
  "stageLabel": "S1 解析"
}
```

## 2.3 获取项目详情

### `GET /api/projects/{id}`

返回最少字段：

```json
{
  "id": "PRJ-001",
  "name": "甘肃华能100MW风电项目",
  "customerName": "华能集团",
  "manager": "张建国",
  "deadline": "2026-05-01",
  "bidType": "技术标",
  "files": [
    "招标文件.pdf"
  ],
  "templateFiles": [
    {
      "id": "TPL-1",
      "name": "技术偏离表模板.docx",
      "sizeLabel": "2.1 MB"
    }
  ],
  "currentStage": 1,
  "stageLabel": "S1 解析"
}
```

## 2.4 阶段条

### `GET /api/projects/{id}/stages`

返回最少字段：

```json
[
  { "id": 1, "name": "解析", "status": "active", "isHuman": false },
  { "id": 2, "name": "目录", "status": "pending", "isHuman": false },
  { "id": 3, "name": "审核目录", "status": "pending", "isHuman": true },
  { "id": 4, "name": "缺口识别", "status": "pending", "isHuman": false },
  { "id": 5, "name": "备料", "status": "pending", "isHuman": true },
  { "id": 6, "name": "审核备料", "status": "pending", "isHuman": true },
  { "id": 7, "name": "填充", "status": "pending", "isHuman": false },
  { "id": 8, "name": "校验", "status": "pending", "isHuman": false },
  { "id": 9, "name": "共创", "status": "pending", "isHuman": true },
  { "id": 10, "name": "导出", "status": "pending", "isHuman": false }
]
```

### `PUT /api/projects/{id}/stages/{stage}`

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
  "stageLabel": "S2 目录生成"
}
```

---

## 3. S1 解析

## 3.1 上传并解析

### `POST /api/projects/{id}/parse-results/upload-and-run`

请求：

- `multipart/form-data`
- `tenderFiles[]`: 招标文件，必选
- `templateFiles[]`: 模板文件，可选

返回最少字段：

```json
{
  "status": "completed",
  "parsedAt": "2026-04-19T10:30:00.000Z",
  "message": "上传成功，已自动解析 1 份招标文件。",
  "project": {
    "id": "PRJ-001",
    "files": [
      "招标文件.pdf"
    ],
    "templateFiles": [
      {
        "id": "TPL-1",
        "name": "技术偏离表模板.docx",
        "sizeLabel": "2.1 MB"
      }
    ],
    "currentStage": 1,
    "stageLabel": "S1 解析"
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

## 3.2 获取解析结果

### `GET /api/projects/{id}/parse-results`

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

---

## 4. S2 目录生成

## 4.1 获取目录生成状态

### `GET /api/projects/{id}/directory-generation`

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

## 4.2 生成目录

### `POST /api/projects/{id}/directory-generation/run`

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
  "tasks": [
    { "id": "task-1", "label": "解析章节线索", "status": "done" },
    { "id": "task-2", "label": "调用目录生成 skill", "status": "done" },
    { "id": "task-3", "label": "保存目录结果", "status": "done" }
  ],
  "message": "目录生成完成"
}
```

---

## 5. S3 目录审核

## 5.1 获取目录审核稿

### `GET /api/projects/{id}/outline`

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
      "children": [
        {
          "id": "OL-1-1",
          "title": "项目背景",
          "children": []
        }
      ]
    }
  ]
}
```

## 5.2 保存目录审核稿

### `PUT /api/projects/{id}/outline`

请求：

```json
{
  "nodes": [],
  "comment": "已确认目录结构"
}
```

返回最少字段：

```json
{
  "outlineVersion": 2,
  "reviewStatus": "draft",
  "summary": {
    "totalNodeCount": 12
  },
  "nodes": [],
  "message": "目录已保存"
}
```

## 5.3 重生成目录审核稿

### `POST /api/projects/{id}/outline/regenerate`

返回最少字段：

```json
{
  "outlineVersion": 3,
  "reviewStatus": "draft",
  "nodes": [],
  "message": "已重生成目录审核稿"
}
```

## 5.4 确认目录

### `POST /api/projects/{id}/outline/confirm`

返回最少字段：

```json
{
  "message": "目录已确认",
  "outlineVersion": 3,
  "reviewStatus": "confirmed"
}
```

---

## 6. S7 初稿生成

## 6.1 获取生成状态

### `GET /api/projects/{id}/fill-generation`

返回最少字段：

```json
{
  "status": "idle",
  "filledAt": "",
  "runDurationSec": 0,
  "runDuration": "",
  "summary": "尚未触发填充，请点击“触发填充”后继续。",
  "output": null
}
```

## 6.2 触发生成

### `POST /api/projects/{id}/fill-generation/run`

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
  "runDurationSec": 79,
  "runDuration": "1分19秒",
  "summary": "初稿生成完成。",
  "output": {
    "fileName": "甘肃华能100MW风电项目_初稿.docx",
    "fileType": "docx",
    "size": "2.8 MB",
    "fileUrl": "/files/DOC-001.docx"
  },
  "sections": [
    {
      "nodeId": "OL-1",
      "title": "项目概况",
      "generationMode": "generated",
      "evidenceRefs": [],
      "riskFlags": []
    },
    {
      "nodeId": "OL-2",
      "title": "企业业绩",
      "generationMode": "placeholder",
      "evidenceRefs": [],
      "riskFlags": [
        "FACT_REQUIRED"
      ]
    }
  ],
  "message": "填充完成"
}
```

说明：

- 当前 MVP 不写 `wiki+db`
- 当前只允许：
  - `generated`
  - `placeholder`
  - `generated_with_placeholder`

---

## 7. S9 文档共创

## 7.1 获取编辑文档

### `GET /api/projects/{id}/document`

返回最少字段：

```json
{
  "status": "ready",
  "documentId": "DOC-001",
  "sourceFileName": "甘肃华能100MW风电项目_初稿.docx",
  "sourceFileUrl": "http://127.0.0.1:8000/files/DOC-001.docx",
  "fileName": "甘肃华能100MW风电项目_初稿.docx",
  "fileType": "docx",
  "fileUrl": "http://127.0.0.1:8000/files/DOC-001.docx",
  "lastSavedAt": "2026-04-19T11:10:00.000Z",
  "version": 1,
  "onlyoffice": {
    "documentKey": "PRJ-001-v1",
    "title": "甘肃华能100MW风电项目_初稿.docx",
    "fileUrl": "http://127.0.0.1:8000/files/DOC-001.docx",
    "callbackUrl": "http://127.0.0.1:8000/api/projects/PRJ-001/document/callback",
    "user": {
      "id": "user-1",
      "name": "当前用户"
    }
  },
  "fallback": {
    "content": "OnlyOffice 不可用时展示的纯文本内容"
  }
}
```

说明：

- 这里不用旧口径 `editorSession`
- 当前前端 S9 页面直接读取顶层 `onlyoffice`

## 7.2 保存回写兜底内容

### `PUT /api/projects/{id}/document/save`

请求：

```json
{
  "content": "修改后的正文内容"
}
```

返回最少字段：

```json
{
  "message": "文档已保存并回写。",
  "payload": {
    "status": "ready",
    "documentId": "DOC-001",
    "fileName": "甘肃华能100MW风电项目_初稿.docx",
    "lastSavedAt": "2026-04-19T11:20:00.000Z",
    "version": 2,
    "onlyoffice": {
      "documentKey": "PRJ-001-v2"
    },
    "fallback": {
      "content": "修改后的正文内容"
    }
  }
}
```

## 7.3 强制回写

### `POST /api/projects/{id}/document/force-save`

返回最少字段：

```json
{
  "message": "已触发保存回写。",
  "payload": {
    "status": "ready",
    "documentId": "DOC-001",
    "lastSavedAt": "2026-04-19T11:22:00.000Z",
    "version": 3,
    "onlyoffice": {
      "documentKey": "PRJ-001-v3"
    }
  }
}
```

## 7.4 OnlyOffice 回调

### `POST /api/projects/{id}/document/callback`

请求：按 OnlyOffice callback 协议

成功返回：

```json
{
  "error": 0
}
```

---

## 8. S10 最终下载

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

---

## 9. 只记这几个核心对象

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

### `DraftSection`

- `nodeId`
- `title`
- `generationMode`
- `evidenceRefs`
- `riskFlags`

### `DocumentWorkspace`

- `documentId`
- `fileName`
- `fileUrl`
- `version`
- `onlyoffice`
- `fallback`

---

## 10. 开发时最重要的 4 句话

1. FastAPI 统一承接所有 `/api`，前端不再直接连 mock-server。
2. `S1` 必须上传真实文件，不是只传文件名或文件元数据。
3. `S2` 和 `S7` 先把接口和返回结构定稳，再逐步接 `opencode skill`。
4. `S9` 先按当前前端的 `onlyoffice` 字段结构实现，不再走旧的 `editorSession` 口径。
