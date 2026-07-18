# bid_fill_generation_state

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/bid_fill_generation_state.py` |
| 层级 | 服务层 |
| 领域 | 项目与状态流 |
| 行数 | 253 |

**职责**: 正文生成运行态 `fill_state` 的纯函数更新集：开始（按标类生成文案与三步任务）/进度更新/失败/结果保存。

## Input / Output
- Input: 项目 dict + percentage/summary/tasks/status/事件/opencode 轨迹。
- Output: `fill_state`：status running→…、三步任务（准备 S2 目录 Wiki 素材库 → 调用拼装 skill → 写入并规范化 Word 正文）、runDurationSec、sections、events。

## 调用链
- **上游**: `bid_generation_flow`、`tech_assembly`（save_fill_generation_result_state）、`business_assembly`。
- **下游**: `bid_fill_state`（默认结构/标签）、`bid_runtime_state`（事件）、`wiki_blueprint_common`。

## 中间数据与状态
- `fill_state` 状态机（idle→running→completed/failed）；陈旧判定阈值在 `bid_generation_flow`（1h）。
