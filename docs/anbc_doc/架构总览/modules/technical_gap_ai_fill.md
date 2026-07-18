# technical_gap_ai_fill

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_gap_ai_fill.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 1123 |

**职责**: 技术缺口 AI 填写执行器：按任务类型走两条 Skill——附表/表格 `bid-tech-table-filler`（schema `bid-tech-table-fill-v1`），正文「待填写」模板 `bid-tech-word-placeholder-filler`（schema `bid-tech-word-placeholder-fill-v1`）；准备源素材、执行、产出质量报告与产物登记。

## Input（输入）
- gap 条目（fillTasks/appendixTasks/来源素材路由）、blankDocx 目标、源素材（docx/xlsx，MinIO 本地化；图片/PDF 走 OCR 兜底）、项目机型。

## Output（输出）
- 填写后的 docx 产物（resolvedArtifacts，source=ai_fill，附 qualityReport/qualityGate——决定 S7 放行）；OnlyOffice 预览 payload；失败显式落事件。

## 调用链
- **上游**: `technical_gap_actions.run_technical_ai_fill_for_gap` ← `technical_gap_service.ai_fill(_all)`。
- **下游**: Skill 两个 filler（subprocess run_from_manifest.py）、`technical_material_store`、`minio_client`、`ocr_service`、`opencode_client`、`technical_gap_domain/state`、`turbine_models`、`workspace_artifacts`。

## 中间数据与状态
- technical workspace 内填写工作目录与产物；qualityReport.status（passed 才自动放行 S7）。
