# route_project_info

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/api/routes/project_info.py` |
| 层级 | 路由层 |
| 领域 | 系统 |
| 行数 | 20 |

**职责**: 「完善项目信息」表单的选项接口，商务/技术两轨各一个（后续接素材库 JSON 索引，当前可静态）。

## Input / Output — 端点清单（2 个）
- `GET /api/business/project-info/options` → `project_info_options("business")`
- `GET /api/technical/project-info/options` → `project_info_options("technical")`
- Output: 客户下拉、风机机型等选项集合（见 `docs/完善项目信息选项前端参数传递.md`）。

## 调用链
- **上游**: 前端项目信息表单（`workspaces/shared/projectInfoForm.js`）。
- **下游**: `services.project_info_options`。

## 中间数据与状态
- 无。
