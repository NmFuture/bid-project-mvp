# route_performance

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/api/routes/performance.py` |
| 层级 | 路由层 |
| 领域 | 业绩库 |
| 行数 | 195（16 个端点） |

**职责**: 业绩库入口（两轨共用，前缀 `/api/materials/performance`）：业绩记录 CRUD、业绩分类（打包）导入与附件管理。

## Input（输入）— 端点清单
| 分组 | 端点 |
|---|---|
| 记录 | GET ``（keyword/customerName/bidType/tag 过滤分页）、POST ``、PUT/DELETE `/{recordId}`、业绩 Word `POST|GET /{recordId}/word` |
| 分类（打包） | GET `/categories`（场景/功率/机型/年份等多维过滤排序）、POST `/categories/preview`（Excel 汇总表预览）、POST `/categories/import`（导入建类）、GET/DELETE `/categories/{id}`（删除需 confirmName）、PATCH `/categories/{id}/status` |
| 附件 | POST `/categories/{id}/attachments`（contract_bundle 等类型）、下载/预览（类级与条目级，OnlyOffice 预览） |

## Output（输出）
- 业绩记录/分类结构；附件 MinIO 流；OnlyOffice 预览会话。

## 调用链
- **上游**: 前端共享页 `/workspace/shared/materials/performance`；缺口填写间接经 `performance_material_resolver` 消费。
- **下游**: `performance_library_service`、`performance_package_service`、`api_utils`。

## 中间数据与状态
- 分类状态 `status=enabled|...`、评审状态 `reviewStatus=draft|...`、scope=standard；附件存 MinIO。
