# bid_parse_state

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/bid_parse_state.py` |
| 层级 | 服务层 |
| 领域 | 项目与状态流 |
| 行数 | 218 |

**职责**: S1 解析进度/结果运行态的纯函数更新集：`parse_progress`（start→update→complete）与解析结果、模板文件状态。

## Input / Output
- Input: 项目 dict + 进度百分比/事件消息/解析结果。
- Output: `parse_progress`：`{status: idle|running|…, percentage, summary, startedAt, completedAt, events, opencodeOutput}`；`update_parse_result_state` / `update_template_files_state` 更新解析结果与模板文件记录；`source_file_type` 文件类型标注（PDF/MD/DOCX）。

## 调用链
- **上游**: `bid_parse_service`、`bid_project_state`、`business_parse_assets`、`workspace_project_access`。
- **下游**: `bid_runtime_state`（事件构造）、`project_stage_flow`（阶段标签）。

## 中间数据与状态
- `parse_progress` 状态机（idle→running→completed/failed）；进度事件流。
