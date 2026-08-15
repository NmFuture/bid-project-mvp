# parse_business_fields

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/parse_business_fields.py` |
| 层级 | 服务层 |
| 领域 | 解析与AI引擎 |
| 行数 | 2321 |

**职责**: 商务标字段构建（parsing-01 自 `parsing.py` 拆出）：FieldSpec 驱动的项目基础信息/响应字段/资格要求/承诺函分析（含语义复核）/评分细则/覆盖度，以及商务解析契约总装。

## 关键符号
- `FieldSpec`、`_build_business_project_basics`、`_build_qualification_requirements`、`_build_business_commitment_analysis`、`_extract_markdown_scoring`、`_build_business_coverage`、`_transform_to_business_contract`。

## 调用链
- **上游**: `parsing` 门面（re-export，契约总装由 `parse_tender_documents` 调用）。
- **下游**: `parse_profiles`、`agent_engine`（承诺函/模板语义复核）、`parse_appendix`（承诺函与模板对齐）。

## 中间数据与状态
- 无持久状态；字段证据（source_file/section/location）随契约产出供前端溯源。
