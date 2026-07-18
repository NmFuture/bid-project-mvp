# bid_ocr_service

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/bid_ocr_service.py` |
| 层级 | 服务层 |
| 领域 | 项目与状态流 |
| 行数 | 68 |

**职责**: OCR 服务的双轨薄封装 `BidOcrService`（实例化 `business_ocr_service` / `technical_ocr_service`）：先做项目归属校验，再把请求转给 `ocr_service`，附带审计元数据。

## Input（输入）
- project_id + 上传文件 bytes/mime + user；`_audit_metadata` 注入项目名/编码/客户/bidType。

## Output（输出）
- OCR 任务列表/详情/候选确认结果（直接透传 `ocr_service` 返回）。

## 调用链
- **上游**: `routes/business.py`、`routes/technical.py` 的 `/ocr/tasks`、`/ocr/candidates/{id}/confirm` 端点。
- **下游**: `bid_project_service`（ensure_project 校验）、`ocr_service`。

## 中间数据与状态
- 无自有状态；OCR 任务状态在 `ocr_service` 侧。
