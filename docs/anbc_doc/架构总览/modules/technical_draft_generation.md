# technical_draft_generation

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_draft_generation.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 28 |

**职责**: 技术标正文生成入口薄层：先做技术标项目归属校验，再委托 `tech_assembly.assemble_tech_bid_for_project_with_progress`。

## 调用链
- **上游**: `bid_generation_flow`（fill_generation 按标类分发）。
- **下游**: `tech_assembly`、`workspace_project_access`。

## 中间数据与状态
- 无。
