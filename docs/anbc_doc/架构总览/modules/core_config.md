# core_config

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/core/config.py` |
| 层级 | 核心配置 |
| 领域 | 系统 |
| 行数 | 219 |

**职责**: 全部环境变量的唯一收口，dataclass `Settings` 单例。

## 关键配置分组
| 分组 | 内容 |
|---|---|
| 目录 | uploads/documents/parsed（容器内 /data/*，三容器共享卷） |
| opencode | base_url（http://opencode:4096）、provider/model（默认 big-pickle）、timeout 1800s、`S1_PARSE_OPENCODE_ENABLED` |
| OnlyOffice | internal_url、backend_base_url、callback token/白名单、下载上限 |
| PostgreSQL | `DATABASE_URL`（asyncpg，库 bidplatform） |
| MinIO | endpoint、密钥、三桶 materials/documents/templates |
| Redis | url、job 锁 TTL 7200s、结果 TTL 86400s、poll 5s |
| Auth | 引导管理员邮箱/密码、会话 TTL 24h |
| 默认模型 | DEFAULT_LLM_*（内部网关回退）、DEFAULT_OCR_*（DeepSeek-OCR） |
| 上传 | 扩展名白名单（pdf/doc/docx/md/txt/xls(x/m)/图片）、单文件上限 30GB |
| S2 | toc 输出文件名 `toc.json` / `toc_evidence.json` |

## 调用链
- **上游**: 几乎全部模块 `from app.core.config import settings`。
- **下游**: 仅 os.environ。

## 中间数据与状态
- `ensure_dirs()` 建三目录；`project_store_backend` 默认 postgres。
