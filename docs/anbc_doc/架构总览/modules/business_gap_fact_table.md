# business_gap_fact_table

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_gap_fact_table.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 931 |

**职责**: 商务标项目事实表（schema `bid-project-fact-table-v1`）的字段规格与构建：内置基础字段规格清单（招标解析字段/投标人字段等，含来源提示与用途标注），从 S1 解析结果 + 投标人档案自动填充。

## Input（输入）
- 项目 dict、S1 解析结果（`business_s1_handoff.business_s1_parse_result`）、投标人全局档案（`load_business_bidder_facts_sync`）。
- 字段规格 `BASIC_BUSINESS_FACT_FIELD_SPECS`：label/category/sourceMode(parse|bidder|manual)/sourceHint（如「招标文件封面/第一章招标公告p8」）/usage（如「承诺函p20」）/required。

## Output（输出）
- `build_project_fact_table` / `empty_project_fact_table`：事实表结构（字段值+来源+确认状态）；`fact_table_value_map` 值映射（AI 草拟/填表消费）；保存归一化 `normalize_business_fact_fields_for_save`。

## 调用链
- **上游**: `business_gap_service`（facts 端点组、AI 草拟/填表数据源）、`business_gap_planning`、`business_assembly`。
- **下游**: `business_bidder_profile`、`business_s1_handoff`、`identity`。

## 中间数据与状态
- `business_gap_state.projectFactTable`（项目 JSONB 内）；schema 版本常量。
