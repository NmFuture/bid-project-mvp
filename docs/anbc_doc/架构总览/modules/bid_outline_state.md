# bid_outline_state

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/bid_outline_state.py` |
| 层级 | 服务层 |
| 领域 | 项目与状态流 |
| 行数 | 294 |

**职责**: 目录生成与大纲审核两个运行态（`directory_state` / `outline_state`）的纯函数更新集：开始/更新/完成/失败/保存/确认/重生成，含从 toc.json 恢复。

## Input（输入）
- 项目 dict + 生成结果/目录节点/事件参数。

## Output（输出）
- `directory_state`：status(completed/…)、percentage、output(fileName/chapterCount)、ruleEvidence、opencodeOutput、events、三步 tasks。
- `outline_state`：`outlineVersion`、`reviewStatus`（draft→confirmed，确认时经 `project_stage_flow.apply_confirmed_outline_stage` 推阶段）、nodes。

## 调用链
- **上游**: `bid_directory_flow`、`outline_generation`（save_generated_outline_state）。
- **下游**: `bid_runtime_state`（事件/默认节点/恢复函数）、`bid_type`、`project_stage_flow`。

## 中间数据与状态
- `directory_state.status`、`outline_state.reviewStatus`（confirmed 是 tech_assembly 装配的前置校验）；恢复函数可从 workspace toc.json 重建。
