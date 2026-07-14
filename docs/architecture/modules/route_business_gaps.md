# route_business_gaps

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/api/routes/business_gaps.py` |
| 层级 | 路由层 |
| 领域 | 商务标 |
| 行数 | 289（19 个端点） |

**职责**: 商务标缺口识别与处理入口；整个 router 挂 `ensure_business_project` 依赖（项目必须存在）。

## Input（输入）— 端点清单（前缀 `/api/business/projects/{id}/business-gaps`）
| 分组 | 端点 |
|---|---|
| 计划 | GET ``（读缺口计划，触发运行时终审），POST `/run`（重跑检测） |
| 事实表 | GET/PUT `/facts`，POST `/facts/build`（AI 构建） |
| 素材 | GET `/selectable-materials?keyword=`，GET `/materials/{id}/preview`、`/content/{filename}` |
| 任务处理 | PATCH `/tasks/{id}`，POST `/toc/{nodeId}/manual-task`，`/tasks/{id}/confirm-artifact`、`/upload`、`/upload-files`（multipart）、`/select-material`、`/select-template`、`/ai-draft`、`/table-fill`、`/sync-artifact-material`，DELETE `/tasks/{id}/artifacts/{aid}` |
| 产物 | GET `/artifacts/{id}/content/{filename}`（本地文件 FileResponse） |

## Output（输出）
- 缺口计划（tasks + decision/status + resolvedArtifacts）、产物记录；异常统一映射（PeripheralError→原状态码，Runtime/ValueError→400，KeyError→404）。

## 调用链
- **上游**: 前端 `BusinessGapRecognition.jsx`。
- **下游**: `business_gap_service`（唯一门面）、`minio_client`（素材内容流）。

## 中间数据与状态
- 任务决策五态：`ready / fill_required / material_required / ai_draft_required / review_required`（初判）+ 运行时终审 `recompute_task_states`；产物 `resolvedArtifacts`；`status=needs_input` 等。
