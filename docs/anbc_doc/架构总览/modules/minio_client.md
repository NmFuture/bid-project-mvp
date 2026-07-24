# minio_client

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/minio_client.py` |
| 层级 | 服务层 |
| 领域 | 基础设施与通用 |
| 行数 | ~300 |

**职责**: MinIO 对象存储的唯一封装单例：桶保障、对象上传（bytes/流/本地文件）、下载响应、复制、预签名等。

## Input（输入）
- `settings.minio_endpoint/access_key/secret_key/minio_buckets`（三桶：bid-materials / bid-documents / bid-templates）。
- 各方法入参：bucket、key、bytes/BinaryIO/Path、content_type。

## Output（输出）
- 对象 key；`get_object_response(bucket, key)` 返回可流式读取的响应（配合 `api_utils.minio_streaming_response` 64KB 分块流出）。

## 调用链
- **上游**: `material_*` 上传下载、`business/technical_material_store`、文档/模板/业绩附件服务、`app_main`（启动 ensure_bucket）、`api_utils`、`business_gaps` 路由。
- **下游**: MinIO 服务（S3 协议）。

## 中间数据与状态
- 无自有状态；日志记录每次上传。桶内 key 组织由各业务服务决定（素材 key 存于 `raw_files.minio_key`）。
