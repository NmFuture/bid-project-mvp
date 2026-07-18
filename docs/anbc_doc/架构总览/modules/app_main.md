# app_main

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/main.py` |
| 层级 | 应用入口 |
| 领域 | 系统 |
| 行数 | 58 |

**职责**: FastAPI 应用装配点：lifespan 启动初始化（建目录、确保 MinIO 桶、引导管理员、建系统设置表）、CORS、全局异常映射、挂载 `api_router`。

## Input（输入）
- 环境变量经 `core/config.settings` 注入；无业务入参。

## Output（输出）
- 运行中的 FastAPI 应用（容器内 :8000）；`KeyError→404`、`PeripheralError→其自带状态码` 的统一 JSON 错误响应。

## 调用链
- **上游**: uvicorn/容器启动。
- **下游**: `api.router`、`core.config`、`services.minio_client`、`services.auth_service.ensure_bootstrap_admin`、`services.system_settings._ensure_tables`、`services.peripheral.PeripheralError`。

## 中间数据与状态
- 启动时确保 MinIO 桶 `bid-materials`/`bid-documents`/`bid-templates` 存在；创建 uploads/documents/parsed 目录。
