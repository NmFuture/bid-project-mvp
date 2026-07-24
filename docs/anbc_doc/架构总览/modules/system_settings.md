# system_settings

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/system_settings.py` |
| 层级 | 服务层 |
| 领域 | 系统 |
| 行数 | 791 |

**职责**: 系统设置服务：LLM 网关与 OCR 模型配置（读写/连通性测试/模型选项清单）、默认模板管理（上传/版本/激活，docx 校验）、健康检查、备份记录。opencode 客户端的运行期模型配置来源。

## Input / Output
- 模型配置 kind=`llm|ocr`（存 `SystemConfig` 表）；测试走 httpx 实连；`get_opencode_model_config_sync()` 供 `opencode_client` 构造。
- 默认模板：类型 technical/business，存 `TemplateAsset` + MinIO `bid-templates`。

## 调用链
- **上游**: `route_settings`、`opencode_client`、`ocr_service`、`business_material_splitter`、`app_main`（启动建表）。
- **下游**: DB `SystemConfig/TemplateAsset/BackupRecord`、`minio_client`、`template_store`（docx 校验）、`audit_service`、httpx。

## 中间数据与状态
- `system_config` 表（模型配置）；模板版本与激活位；内置 LLM 模型选项清单（deepseek 系/big-pickle 等）。
