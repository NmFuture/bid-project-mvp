# fe_stage_flows（businessStageFlow + technicalStageFlow）

| | |
|---|---|
| 源文件 | `code/sewpg-bid-frontend/src/workspaces/{business/businessStageFlow.js, technical/technicalStageFlow.js}` |
| 层级 | 前端逻辑 |
| 领域 | 共享 |
| 行数 | 36 + ~40 |

**职责**: 阶段号→路由/文案映射：阶段 1→`/template-directory`、2→`/outline`、3/4→`/gaps`、5/6→`/editor`；商务侧紧凑标签（目录生成/审核目录/素材匹配/共创导出）。与后端 `project_stage_flow.py` 的阶段定义一一对应。

## 调用链
- **上游**: 项目列表（点击进对应阶段页）、入口重定向页、阶段进度组件。
- **下游**: `utils/workspace.projectRoute`。
