# derive_rules

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/derive_rules.py` |
| 层级 | 服务层 |
| 领域 | 解析与AI引擎 |
| 行数 | 89 |

**职责**: 核心事实推导规则纯函数：总装机容量=单机容量×台数等数值闭合推导（`DerivedFact` 含 rule 与 sources 可追溯）与闭合校验 `check_numeric_closure`。

## 调用链
- **上游**: `gap_reviewer`。
- **下游**: 无。

## 中间数据与状态
- 无；推导结果带来源字段（可验证性规约的体现）。
