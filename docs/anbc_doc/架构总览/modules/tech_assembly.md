# tech_assembly

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/tech_assembly.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 大型 |

**职责**: 技术标 S4 正文装配：准备工作目录（toc.json、缺口计划、Wiki 导出、素材），调用 Skill `bid-tech-assembler`（命令 s7assemble）拼装正文 docx，再经 `bid-tech-format-cleaner` 做格式清理，产物落文档存储。

## Input（输入）
- `assemble_tech_bid_for_project_with_progress(project_id, data, progress_callback)`；前置校验：`outline_state.reviewStatus == "confirmed"`（目录必须已确认）。
- 输入物料：outline_state、parse_storage、模板件、缺口计划（含 S7-ready 产物过滤 `technical_gap_artifact_is_s7_ready`）、Wiki 导出（`wiki_export.export_wiki`，并把 gap 计划卡片并入 Wiki）。

## Output（输出）
- 装配后的正文 docx（写 `onlyoffice_documents.document_path` / MinIO）；`fill_state` 结果落运行态（`save_fill_generation_result_state`）；评审 payload（`build_technical_review_payload`）。

## 调用链
- **上游**: `technical_draft_generation` ← `bid_generation_flow`（fill_generation job）。
- **下游**: Skill `bid-tech-assembler`、`bid-tech-format-cleaner`（subprocess run_from_manifest.py）、`technical_gap_repository/domain/state/review`、`technical_material_store`、`turbine_models`、`workspace_artifacts`（stage 工作目录）、`wiki_export`、`minio_client`、`onlyoffice_documents`。

## 中间数据与状态
- 项目 workspace stage 工作目录（toc.json / gap_plan / wiki 目录）；`fill_state`；装配统计（Counter 计数、耗时）。
