# file_utils

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/file_utils.py` |
| 层级 | 服务层 |
| 领域 | 基础设施与通用 |
| 行数 | 75 |

**职责**: 通用工具：文件名/路径段安全化（`safe_filename/safe_segment`）、大小标签格式化、展示时间、`run_awaitable_sync`（同步上下文跑协程，独立线程 event loop）。

## 调用链
- **上游**: 极广（bid_parse_service、gap 域、素材域、system_settings、template_store 等）。
- **下游**: 无。

## 中间数据与状态
- 无。
