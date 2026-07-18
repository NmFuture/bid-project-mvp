# project_info_options

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/project_info_options.py` |
| 层级 | 服务层 |
| 领域 | 系统 |
| 行数 | 90 |

**职责**: 「完善项目信息」表单选项的静态提供者：客户下拉（华润/中电建/…/其他，22 项）、风机机型选项（EW 系列）、基础形式等，按轨返回。文档说明后续将接素材库 JSON 索引动态化（见 `docs/完善项目信息选项前端参数传递.md`）。

## 调用链
- **上游**: `route_project_info`（双轨 options 端点）。
- **下游**: 无。

## 中间数据与状态
- 静态常量选项表。
