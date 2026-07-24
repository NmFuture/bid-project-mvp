# route_technical

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/api/routes/technical.py` |
| 层级 | 路由层 |
| 领域 | 技术标 |
| 行数 | 1047（约 100 个端点） |

**职责**: 技术标全业务入口：项目/阶段、S1 解析、OCR、目录（含 SSE 流）、缺口与 AI 填写、覆盖率、正文生成、文档共创/导出、素材库（含 JSON 索引/标签导入/批量操作）、证书台账、Wiki、审计。

## Input（输入）— 端点分组清单
| 分组 | 端点（前缀 `/api/technical`） |
|---|---|
| 项目 | 同商务标同构（projects CRUD、stages、template-fallback、materials-path、parse-status） |
| OCR | 同商务标同构（tasks、candidates confirm） |
| S1 解析 | `/parse-results/upload-and-run`、`/run`（免上传重跑）、`/template-files/upload`、results/progress、附表 preview/file/callback/approve（单项+全量） |
| 目录 | GET `/directory-generation` + **`/stream`（SSE 进度）** + POST `/run`；GET/PUT `/outline`、POST `/outline/regenerate|confirm`、tender-files file/callback |
| 缺口 | GET/POST `/gaps-detection(/run)`，GET `/gaps`，PUT `/gaps/{id}`，POST `/gaps/recheck`、`/gaps/submit-review`；处理：`/gaps/{id}/upload|select-material|ai-fill`、`/gaps/ai-fill-all`、产物 `artifacts/{id}/content`+`confirm`；事实表 GET/PUT `/gaps/facts` + `/facts/build`；缺料台账 `materials/submissions`（GET/POST）、PATCH `materials/missing/{id}` |
| 生成/覆盖率 | GET/POST `/fill-generation(/run)`；GET `/coverage` |
| 文档 | document 同构 + **`/document/force-save`**、`technical-format`；final-document Word/PDF；**`/export/check` + POST `/export`** |
| 素材库 | 同构 CRUD/upload/move/split/cleaned + 技术标特有：`materials/index`（JSON 索引，空则重建）、PUT `index/tags`、`turbine-model-options`、`raw/folders/bootstrap`、`tag-import/preview|commit`（Excel 导入，支持模糊）、`batch-delete`、`batch-tags`、`certificate-time/batch`、`preview-content` |
| 证书台账 | `materials/certificates`（台账/suggestions/scopes/incremental/{id} recognize/patch/delete/bulk-delete）、`wiki/certificate-time` |
| Wiki | 同商务标同构（bootstrap、节点 CRUD/move、附件、refresh-summary） |
| 审计 | `/audit(/export|/{id})` |

## Output（输出）
- JSON / FileResponse / MinIO 流 / SSE 流；生成类端点入 Redis 队列。

## 调用链
- **上游**: 前端 `workspaces/technical/pages/*`、OnlyOffice 回调。
- **下游**: `technical_project_service`、`technical_parse_service`、`technical_ocr_service`、`technical_directory_service`、`technical_gap_service`、`technical_generation_service`、`technical_coverage_service`/`technical_export_service`（delivery）、`technical_document_service`、`technical_material_store`、`technical_material_index`、`technical_wiki_generation`、`technical_audit_service`。

## 中间数据与状态
- 缺口决策两层（初判+终审）：`ready/fill_required/review_required/material_required`；素材 JSON 索引 `technical_material_index.json`；证书台账挂素材 ext 字段。
