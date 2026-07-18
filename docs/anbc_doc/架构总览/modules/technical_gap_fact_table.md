# technical_gap_fact_table

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_gap_fact_table.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 1419 |

**职责**: 技术标项目事实表构建（schema `bid-project-fact-table-v1`）：从项目字段 + 事实素材文件（docx 表格/xlsx，`project_fact_materials` 准备）抽取「标签: 值」事实，含表头词过滤与常用事实标签词表。

## Input（输入）
- 项目 dict、事实素材文件（docx/xlsx，openpyxl/python-docx 解析）、机型、素材范围。
- 词表：`FACT_TABLE_HEADER_WORDS`（表头噪声过滤）、`COMMON_PROJECT_FACT_LABELS`（项目名称/招标编号/投标机型等）。

## Output（输出）
- 事实表结构（字段值+来源+确认状态，`confirmed` 状态参与 AI 填写取值）；保存归一化与摘要函数。

## 调用链
- **上游**: `technical_gap_service`（facts 端点组）。
- **下游**: `project_fact_materials`、`technical_material_store`、`identity`、`turbine_models`、`file_utils`。

## 中间数据与状态
- `gap_state.projectFactTable`；事实素材本地化临时文件。
