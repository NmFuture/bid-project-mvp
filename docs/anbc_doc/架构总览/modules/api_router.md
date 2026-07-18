# api_router

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/api/router.py` |
| 层级 | 路由层 |
| 领域 | 系统 |
| 行数 | 15 |

**职责**: 汇总注册 9 个路由模块：system、auth、dashboard、performance、project_info、business、business_gaps、technical、settings。

## Input / Output
- 无逻辑，纯 include_router 装配。

## 调用链
- **上游**: `app/main.py`。
- **下游**: `api/routes/` 全部 9 个文件。

## 中间数据与状态
- 无。
