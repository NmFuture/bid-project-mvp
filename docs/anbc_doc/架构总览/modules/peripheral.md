# peripheral

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/peripheral.py` |
| 层级 | 服务层 |
| 领域 | 基础设施与通用 |
| 行数 | 30 |

**职责**: 收敛为两个对外符号：① `PeripheralError`——全后端统一业务异常（status_code+detail+code+extra，`app_main` 全局映射为 JSON 响应）；② `now_day()`——日期串工具。原内存 `PeripheralStore` 与种子数据已删除（deadcode-01），真实实现为 `material_store.MaterialStore`。

## Input / Output
- `PeripheralError.to_payload()`：`{detail, code, ...extra}`。

## 调用链
- **上游**: 几乎全部服务与路由（异常类）；`audit_service` 等（`now_day`）。
- **下游**: 无。

## 中间数据与状态
- 错误码规约（如 RAW_FILE_NOT_FOUND、TECHNICAL_PROJECT_REQUIRED）分散在各调用点，此处是异常类型唯一定义。
