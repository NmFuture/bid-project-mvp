# business_assembly

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_assembly.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 851 |

**职责**: 商务标响应文件装配：准备 toc/模板/事实表/素材输入，调用 Skill `bid-business-assembler`（命令 businessassemble）拼装正文，格式化走 Skill `bid-business-format-cleaner`（businessformat）；并定义格式预设 `BUSINESS_FORMAT_PRESETS`（standard 标准 / compact 紧凑，当前复用同一清洗规则）。

## Input（输入）
- `assemble_business_bid_for_project_with_progress(project_id, data, progress_callback)`；输入物料：toc（`_resolve_business_toc_json`）、模板索引、S1 解析结果、项目事实表、素材库。

## Output（输出）
- 装配后的正文 docx（`onlyoffice_documents.document_path` + MinIO）；`fill_state` 结果（`save_fill_generation_result_state`）；格式预设套用结果（供 `business_document_service`）。

## 调用链
- **上游**: `business_draft_generation` ← `bid_generation_flow`（fill_generation job）；`business_document_service`（格式预设）。
- **下游**: Skill `bid-business-assembler`/`bid-business-format-cleaner`（subprocess）、`business_gap_planning`（toc/模板解析复用）、`business_gap_fact_table`、`business_material_store`、`business_s1_handoff`、`opencode_client`、`minio_client`、`workspace_artifacts`。

## 中间数据与状态
- workspace 装配工作目录；`fill_state`；`BUSINESS_FORMAT_PRESETS` 常量。
