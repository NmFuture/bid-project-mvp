# api_utils

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/api/utils.py` |
| 层级 | 路由层工具 |
| 领域 | 系统 |
| 行数 | 154 |

**职责**: 路由层公共工具：MinIO 对象流式响应、OnlyOffice 回访后端地址推断（本机开发时探测局域网 IP / host.docker.internal）、Content-Disposition 构造。

## Input（输入）
- `minio_streaming_response(payload)`：payload 需含 `bucket`/`key`/`fileName`/`mimeType`（由各 service 返回）。
- `onlyoffice_backend_base_url(request)`：当前请求 URL + `ONLYOFFICE_BACKEND_BASE_URL` 配置。

## Output（输出）
- `StreamingResponse`（64KB 分块流出 MinIO 对象，attachment/inline 两种）。
- OnlyOffice 可回访的后端绝对地址字符串。

## 调用链
- **上游**: `routes/business.py`、`routes/technical.py`、`routes/performance.py`、`routes/business_gaps.py` 等下载/预览端点。
- **下游**: `services.minio_client`、`core.config`。

## 中间数据与状态
- `detect_lan_ip` 结果 lru_cache 缓存（进程级）。
