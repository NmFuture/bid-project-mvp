# 当前 API 接口核心版

> 用途：记录当前 `Web -> FastAPI` 的接口口径。
> 更新日期：2026-05-27

本文件根据当前代码整理，不再沿用旧 MVP 单线接口。

真实代码来源：

- 前端封装：`../sewpg-bid-frontend/src/api/index.js`
- 商务标后端：`../sewpg-bid-backend/app/api/routes/business.py`
- 商务标缺口：`../sewpg-bid-backend/app/api/routes/business_gaps.py`
- 技术标后端：`../sewpg-bid-backend/app/api/routes/technical.py`
- 通用后端：`../sewpg-bid-backend/app/api/routes/auth.py`、`settings.py`、`dashboard.py`、`system.py`

## 1. 当前原则

- 业务接口按标类分开：`/api/business/...`、`/api/technical/...`。
- 前端业务页面只通过 `src/api/index.js` 的 facade 调用接口。
- 当前研发先跑通商务标端到端；技术标接口先保持现状。
- 旧 `/api/projects...`、旧单线 `/api/materials...`、旧 MVP 阶段接口不再作为当前入口。

## 2. 前端 API Facade

| 类型 | 前端 facade | 后端前缀 |
| --- | --- | --- |
| 商务项目 | `businessProjectsAPI` | `/api/business/projects` |
| 商务阶段 | `businessStagesAPI` | `/api/business/projects/{project_id}/stages` |
| 商务解析 | `businessParseAPI` | `/api/business/projects/{project_id}/parse-results` |
| 商务目录生成 | `businessDirectoryAPI` | `/api/business/projects/{project_id}/directory-generation` |
| 商务目录审核 | `businessOutlineAPI` | `/api/business/projects/{project_id}/outline` |
| 商务素材匹配/AI填写 | `businessGapsAPI` | `/api/business/projects/{project_id}/business-gaps` |
| 商务正文/共创/导出 | `businessGenerateAPI`、`businessDocumentAPI` | `/api/business/projects/{project_id}/fill-generation`、`document`、`final-document` |
| 商务素材库/Wiki | `businessMaterialsAPI` | `/api/business/materials` |
| 技术标 | `technical*API` | `/api/technical/...` |
| 通用设置 | `settingsAPI` | `/api/settings/...` |
| 登录 | `authAPI` | `/api/auth/...` |
| 仪表盘 | `dashboardAPI` | `/api/dashboard` |

## 3. 商务标主链路接口

| 环节 | 主要接口 | 说明 |
| --- | --- | --- |
| 项目 | `GET/POST /api/business/projects`、`GET/PUT/DELETE /api/business/projects/{project_id}` | 商务标项目管理。 |
| 智能解析 | `GET /parse-results`、`GET /parse-results/progress`、`POST /parse-results/upload-and-run` | 上传招标文件并生成解析结果。 |
| 解析附件审核 | `GET/POST /parse-results/appendices...`、`commitment-letters...`、`business-scoring/approve` | 附件空表、承诺函、商务评分等解析资产预览和确认。 |
| 模板上传 | `POST /api/business/projects/{project_id}/template-files/upload` | 上传项目模板。 |
| 目录生成 | `GET /directory-generation`、`POST /directory-generation/run` | 生成商务标目录。 |
| 目录审核 | `GET/PUT /outline`、`POST /outline/confirm` | 人工审核目录。 |
| 素材匹配 | `GET/POST /business-gaps`、`GET /selectable-materials`、`POST /tasks/{task_id}/select-material` | 固定素材、AI填写、人工补充三类处理。 |
| 项目事实表 | `GET /business-gaps/facts`、`POST /facts/build`、`PUT /facts` | 生成和保存商务事实表。 |
| AI填写 | `POST /business-gaps/tasks/{task_id}/table-fill` | 根据待填写文件、来源素材和事实表生成填写产物。 |
| 人工补充 | `POST /tasks/{task_id}/upload`、`upload-files`、`manual-task` | 人工上传、补充或创建任务。 |
| 正文生成 | `GET /fill-generation`、`POST /fill-generation/run` | 生成商务标正文。 |
| 在线共创 | `GET /document`、`PUT /document/save`、`POST /document/business-chat` | OnlyOffice 编辑和 AI 辅助修改。 |
| 格式处理 | `POST /document/business-format` | 调用商务格式处理。 |
| 导出 | `GET /final-document`、`GET /final-document/file`、`GET /final-document/pdf`、`GET /final-document/pdf/file` | 导出 Word/PDF。 |

上表里的 `/parse-results` 等短路径均省略前缀 `/api/business/projects/{project_id}`。

## 4. 商务素材库和 Wiki 接口

| 能力 | 主要接口 | 说明 |
| --- | --- | --- |
| 身份范围 | `GET /api/business/materials/identity-options` | 获取通用素材、客户素材、项目素材等范围选项。 |
| 原始素材树 | `GET /api/business/materials/raw/tree`、`GET /raw/files` | 查看素材目录和文件。 |
| 上传/目录 | `POST /raw/upload`、`POST /raw/folders`、`DELETE /raw/folders` | 上传素材、建目录、删目录。 |
| 素材元数据 | `PATCH /raw/{file_id}` | 更新素材信息；本轮需要支持多标签。 |
| 素材移动/删除 | `POST /raw/move`、`POST /raw/folders/move`、`DELETE /raw/{file_id}` | 移动或删除素材。 |
| 素材预览 | `GET /raw/{file_id}/content`、`GET /raw/{file_id}/cleaned/preview`、`GET /raw/{file_id}/cleaned/content` | 查看原文、清洗稿。 |
| 商务拆分 | `POST /raw/{file_id}/business-split/preview`、`POST /raw/{file_id}/business-split/confirm` | 商务素材拆分预览和确认。 |
| Wiki | `GET/POST /api/business/materials/wiki`、`PUT/DELETE /wiki/{node_id}` | 商务 Wiki 节点管理。 |
| Wiki 附件 | `POST /wiki/{node_id}/attachments`、`DELETE /wiki/attachments/{attachment_id}`、`GET /wiki/attachments/{attachment_id}/content` | Wiki 附件管理和预览。 |
| Wiki 摘要 | `POST /wiki/{node_id}/refresh-summary` | 重新生成素材摘要。 |

## 5. 技术标接口

技术标仍按 `/api/technical/...` 保留完整双轨接口：

- 项目：`/api/technical/projects...`
- 智能解析：`/api/technical/projects/{project_id}/parse-results...`
- 目录生成和审核：`directory-generation`、`outline`
- 缺口处理和 AI填写：`gaps`、`gaps/facts`、`gaps/{gap_id}/ai-fill`
- 正文、格式和导出：`fill-generation`、`document`、`final-document`
- 技术素材库/Wiki：`/api/technical/materials...`
- 审计：`/api/technical/audit...`

本轮不展开技术标质量提升，只保证商务标改动不破坏技术标入口。

## 6. 通用接口

| 能力 | 主要接口 |
| --- | --- |
| 健康检查 | `/healthz`、`/api/healthz` |
| 登录 | `POST /api/auth/login`、`GET /api/auth/me`、`POST /api/auth/logout` |
| 客户选项 | `GET /api/customers/key-accounts` |
| 仪表盘 | `GET /api/dashboard` |
| 用户设置 | `/api/settings/users...` |
| LLM 设置 | `/api/settings/llm-gateway...` |
| OCR 设置 | `/api/settings/ocr...` |
| 默认模板 | `/api/settings/default-templates...` |

## 7. 本轮要补的接口能力

| 能力 | 当前处理 |
| --- | --- |
| 原始素材多标签 | 复用 `PATCH /api/business/materials/raw/{file_id}` 扩展元数据。 |
| 共用业绩库 | 需要新增后端 service/API，前端增加入口。 |
| 素材匹配输入 | 扩展 `POST /api/business/projects/{project_id}/business-gaps/run` 的 manifest 输入。 |
| AI填写 | 继续使用 `POST /api/business/projects/{project_id}/business-gaps/tasks/{task_id}/table-fill`，明确待填写文件、来源素材、事实表和输出文件。 |
