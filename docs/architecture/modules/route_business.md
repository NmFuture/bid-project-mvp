# route_business

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/api/routes/business.py` |
| 层级 | 路由层 |
| 领域 | 商务标 |
| 行数 | 753（约 70 个端点） |

**职责**: 商务标全业务入口（除缺口外）：项目 CRUD/阶段、S1 解析与资产确认、OCR、目录生成与审核、正文生成、文档共创/导出、素材库、Wiki、审计。

## Input（输入）— 端点分组清单
| 分组 | 端点（前缀 `/api/business`） |
|---|---|
| 项目 | GET/POST `/projects`，GET/PUT/DELETE `/projects/{id}`，`/materials-path`，GET/PUT `/template-fallback`，GET `/stages` + PUT `/stages/{stage}`，`/materials/parse-status` |
| OCR | GET/POST `/projects/{id}/ocr/tasks`，GET `/ocr/tasks/{taskId}`，POST `/ocr/candidates/{id}/confirm` |
| S1 解析 | POST `/parse-results/upload-and-run`（tenderFiles+templateFiles），POST `/template-files/upload`，GET `/parse-results`、`/progress` |
| 解析资产确认 | 附表/承诺函：`preview`、`file(/{filename})`（GET/HEAD）、OnlyOffice `callback`、单项与全量 `approve`；商务评分 `business-scoring/approve` |
| 目录 | GET `/directory-generation` + POST `/run`；GET/PUT `/outline` + POST `/outline/confirm`；招标原文 `outline/tender-files/{id}/file` + `callback` |
| 正文生成 | GET `/fill-generation` + POST `/run` |
| 文档共创 | GET `/document`，PUT `/document/save`，`/document/file(/{name})`，POST `/document/callback`，AI：`business-chat`、`business-rewrite/suggest|apply`、`business-format` |
| 终稿导出 | GET `/final-document`、`/file`、`/pdf`、`/pdf/file` |
| 素材库 | `materials/identity-options`、`raw/tree`、`raw/files`（多维过滤）、`raw/upload`（multipart/JSON 双态）、`raw/folders` 增删移、文件 PATCH/DELETE/`download`/`content`/`move`、AI 拆分 `business-split/preview|confirm`、清洗 `cleaned/preview|content` |
| Wiki | `materials/wiki` 列表、`bootstrap`、节点 CRUD/move、附件上传下载删除、`refresh-summary` |
| 审计 | GET `/audit`、`/audit/export`、`/audit/{id}` |

## Output（输出）
- JSON 业务结构 / FileResponse / MinIO StreamingResponse；目录与正文生成端点返回 202 类状态并入 Redis 队列。

## 调用链
- **上游**: 前端 `workspaces/business/pages/*` 与 OnlyOffice 回调。
- **下游**: `business_project_service`、`bid_parse_service.business_parse_service`、`bid_ocr_service`、`business_directory_service`、`business_generation_service`、`business_document_service`、`business_material_store`、`business_wiki_generation`、`business_audit_service`、`material_tags`。

## 中间数据与状态
- 间接：项目运行态（parse/directory/fill/document state）、Redis 队列、MinIO 三桶。路由层自身无状态。
