# technical_gap_repository

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_gap_repository.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 39 |

**职责**: 技术缺口域项目访问薄层：读/写技术标项目运行态，错误语义 `TECHNICAL_PROJECT_NOT_FOUND`(404) / `TECHNICAL_PROJECT_REQUIRED`(400)。与商务侧对称。

## 调用链
- **上游**: `technical_gap_service`、`tech_assembly`。
- **下游**: `workspace_project_access`、`peripheral`。

## 中间数据与状态
- 无自有状态。
