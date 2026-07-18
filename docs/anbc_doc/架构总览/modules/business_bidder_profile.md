# business_bidder_profile

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_bidder_profile.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 76 |

**职责**: 投标人（我方）全局事实档案的读写：投标人名称等键值对，存 SystemConfig 表（key=`business_bidder_facts`），非 postgres 模式退化为进程内 dict（测试隔离）。

## Input / Output
- `load_business_bidder_facts()` → `{标签: 值}`；`store_business_bidder_facts(values)` 清洗（去空键空值）后落库。

## 调用链
- **上游**: `business_gap_service`、`business_gap_fact_table`、`business_gap_planning`（AI 草拟/事实表的投标人字段来源）。
- **下游**: DB 表 `SystemConfig`（models.materials，async_session）、`file_utils.run_awaitable_sync`。

## 中间数据与状态
- `system_config` 表 key=`business_bidder_facts`；memory 模式 `_memory_profile`。
