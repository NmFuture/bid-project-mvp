# dashboard_service

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/dashboard_service.py` |
| 层级 | 服务层 |
| 领域 | 系统 |
| 行数 | 159 |

**职责**: 工作台数据构建：汇总两轨项目为卡片（阶段 S0-S6 映射进度 0.10~1.00），统计进行中/已交付数量，按用户组装工作台。

## 调用链
- **上游**: `route_dashboard`。
- **下游**: `bid_project_service`（两轨实例的项目列表）。

## 中间数据与状态
- `_STAGE_PROGRESS` 阶段→进度映射（注意：仪表盘沿用 S0-S6 旧阶段号做进度估算）。
