# peripheral

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/peripheral.py` |
| 层级 | 服务层 |
| 领域 | 基础设施与通用 |
| 行数 | 1099 |

**职责**: 两个角色合一：① `PeripheralError`——全后端统一业务异常（status_code+detail+code+extra，`app_main` 全局映射为 JSON 响应）；② 外围模块的轻量状态承接与 fixture 数据（历史遗留的内存 PeripheralStore，正被真实实现替换）。

## Input / Output
- `PeripheralError.to_payload()`：`{detail, code, ...extra}`。
- fixture/内存承接：素材根路径推导等（经 `material_folder_scope`）。

## 调用链
- **上游**: 几乎全部服务与路由（异常类）；`routes/technical.py`、`bid_ocr_service` 等（错误语义）。
- **下游**: `bid_type`、`material_folder_scope`。

## 中间数据与状态
- 错误码规约（如 RAW_FILE_NOT_FOUND、TECHNICAL_PROJECT_REQUIRED）分散在各调用点，此处是异常类型唯一定义。
