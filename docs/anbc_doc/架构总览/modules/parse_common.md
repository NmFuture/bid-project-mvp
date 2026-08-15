# parse_common

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/parse_common.py` |
| 层级 | 服务层 |
| 领域 | 解析与AI引擎 |
| 行数 | 114 |

**职责**: S1 解析通用小件（parsing-01 自 `parsing.py` 拆出）：取消检查、parsed 目录路径约定、文本归一、带心跳的进度执行器与协程阻塞桥。

## 关键符号
- `_raise_if_parse_cancelled`、`parsed_project_dir`、`parsed_appendix_path`、`_normalize_text`、`_run_with_progress_heartbeat`、`_run_coroutine_blocking`。

## 调用链
- **上游**: `parsing` 门面（re-export 保持旧符号可 patch）、`parse_extract`、`parse_appendix`、`parse_s1_skill`。
- **下游**: `bid_parse_cancel.ParseCancelledError`。

## 中间数据与状态
- 无持久状态；心跳间隔默认 10s。
