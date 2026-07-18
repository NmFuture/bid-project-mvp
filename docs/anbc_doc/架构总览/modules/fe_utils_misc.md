# fe_utils_misc（branding + outlineNumber）

| | |
|---|---|
| 源文件 | `code/sewpg-bid-frontend/src/utils/{branding.js, outlineNumber.js}` |
| 层级 | 前端工具 |
| 领域 | 共享 |
| 行数 | 13 + 2 |

**职责**: 两个微工具：`brandFutureCode`——把后端返回文案中的 "opencode" 统一替换为对外品牌名 "futurecode"；`getOutlineDisplayNumber`——目录节点编号取值兼容（tocNumber/number/toc_number）。

## 调用链
- **上游**: 目录/生成相关页面（展示 LLM 轨迹与目录编号处）。
- **下游**: 无。
