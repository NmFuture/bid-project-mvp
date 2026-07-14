# fe_utils_stageLocking

| | |
|---|---|
| 源文件 | `code/sewpg-bid-frontend/src/utils/stageLocking.js` |
| 层级 | 前端工具 |
| 领域 | 共享 |
| 行数 | 45 |

**职责**: 阶段锁定规则：`getActiveStageId(stages)`（active 优先，否则最高 completed+1，上限 6）与 `getStrictStageLockReason`（目标阶段在当前 active 之后 → 返回「请先完成当前阶段：xxx」锁定文案）。

## 调用链
- **上游**: 项目内各阶段页面（进入受限阶段时提示）。
- **下游**: 无。

## 中间数据与状态
- 纯函数；stage 状态来自后端 `GET .../stages`。
