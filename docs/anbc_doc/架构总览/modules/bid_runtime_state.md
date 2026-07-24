# bid_runtime_state

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/bid_runtime_state.py` |
| 层级 | 服务层 |
| 领域 | 项目与状态流 |
| 行数 | 大型 |

**职责**: 项目运行态的默认值、事件与恢复规则的唯一归属：解析/目录/正文/文档各 state 的空结构构造、事件构造、`now_iso` 时间戳唯一出处、workspace JSON 原子读写。

## Input（输入）
- 项目 dict（store 加载）；workspace 目录（经 `workspace_artifacts` 定位）内的既有 JSON（如 toc.json）用于运行态恢复。

## Output（输出）
- `empty_parse_result` / `default_outline_nodes` 等各运行态默认结构；`build_parse_event` / `build_directory_event`（`{at, level, step, message}`）；`build_directory_opencode_output`（LLM 执行轨迹壳：status/sessionId/parts）。
- `write_json_file_atomic`：临时文件 + os.replace 原子写。

## 调用链
- **上游**: `store`（ensure_project_runtime_states）、`bid_parse_state`/`bid_outline_state`/`bid_fill_state`/`bid_document_state` 等状态模块、两轨 service。
- **下游**: `bid_type`、`workspace_artifacts`、`core.config`。

## 中间数据与状态
- 各运行态子结构：`parse_state`（status: idle→…）、`directory_state`、`fill_state`、`document_state`；事件流数组；opencodeOutput 轨迹。运行态可从项目 workspace 下既有 `toc.json` 恢复（与商务/技术两轨行为对齐）。
