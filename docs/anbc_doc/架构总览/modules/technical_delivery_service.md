# technical_delivery_service

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_delivery_service.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 124 |

**职责**: 技术标交付服务两件套：`TechnicalCoverageService`（覆盖率查询）与 `TechnicalExportService`（导出前检查——覆盖率红项须为 0 + 版本锁定警示，然后执行导出）。

## Input / Output
- Input: project_id；导出请求。
- Output: 覆盖率结构；`check`：`{checks:[覆盖率校验(passed=noCover==0), 项目信息一致性...], warnings:[版本锁定提示]}`；`export`：终稿导出。

## 调用链
- **上游**: `routes/technical.py`（`/coverage`、`/export/check`、`/export`）。
- **下游**: `technical_coverage`、`bid_project_service`、`url_utils`。

## 中间数据与状态
- 无自有状态；导出检查是共创导出阶段的门禁。
