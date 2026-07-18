# route_settings

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/api/routes/settings.py` |
| 层级 | 路由层 |
| 领域 | 系统 |
| 行数 | 142（13 个端点，全部要求登录） |

**职责**: 系统设置：用户管理、LLM 网关与 OCR 模型配置（含连通性测试）、默认模板管理、健康检查。

## Input（输入）— 端点清单
| 分组 | 端点 |
|---|---|
| 用户 | GET/POST `/api/settings/users`，PUT `/users/{id}` |
| LLM 网关 | GET/PUT `/llm-gateway`，POST `/llm-gateway/test` |
| OCR | GET/PUT `/ocr`，POST `/ocr/test` |
| 默认模板 | GET/POST `/default-templates`（multipart 或 base64 JSON），POST `/default-templates/{id}/activate` |
| 健康 | GET `/health` |

## Output（输出）
- 配置读写结果（LLM 返回时补 endpoint/modelId 兼容字段）；模板版本记录与激活状态。

## 调用链
- **上游**: 前端 Settings 页。
- **下游**: `auth_service`（用户）、`system_settings_service`（模型配置/模板/健康）。

## 中间数据与状态
- 系统设置表（`system_settings._ensure_tables` 启动建表）；模型配置 kind=`llm|ocr`；模板默认版本号 `2026.04`。
