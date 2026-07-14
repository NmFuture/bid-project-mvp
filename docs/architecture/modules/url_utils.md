# url_utils

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/url_utils.py` |
| 层级 | 服务层 |
| 领域 | 基础设施与通用 |
| 行数 | 116 |

**职责**: URL 工具（与 `api/utils.py` 同源逻辑的服务层版本）：绝对地址构建、OnlyOffice 回访后端地址推断（本机开发探测局域网 IP / host.docker.internal）、消息 payload 构造。

## 调用链
- **上游**: `bid_document_flow`、`bid_parse_service`、`bid_directory_flow`、两轨 document_service、`business_gap_service`、`technical_delivery_service`。
- **下游**: `core.config`。

## 中间数据与状态
- `detect_lan_ip` lru_cache。
