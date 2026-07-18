# bid_fill_state

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/bid_fill_state.py` |
| 层级 | 服务层 |
| 领域 | 项目与状态流 |
| 行数 | 66 |

**职责**: 正文生成运行态 `fill_state` 的默认结构与标签工厂：按项目标类生成任务标签（「调用{标类}正文拼装 skill」）与三步任务清单。

## Input / Output
- Input: 项目 dict（读 bidType）。
- Output: `default_fill_state()`：`{status: idle, percentage, filledAt, runDurationSec, summary, output, sections, opencodeOutput, events, tasks}`；三步任务：准备 S2 目录/Wiki/素材库 → 调用拼装 skill → 写入 Word 正文。

## 调用链
- **上游**: `bid_fill_generation_state`、`bid_project_state`（运行态初始化）。
- **下游**: `bid_type`。

## 中间数据与状态
- `fill_state` 默认结构与任务三步模型（status: pending→…）。
