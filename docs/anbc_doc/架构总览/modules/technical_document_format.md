# technical_document_format

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_document_format.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 187 |

**职责**: 技术标格式化预设执行：`TECH_FORMAT_PRESETS`（standard 标准 / custom 自定义样式覆盖），对当前正文 docx 复用 `tech_assembly` 的本地格式清洗管线（toc/outline 准备 + format-cleaner）。

## Input / Output
- Input: `apply_technical_document_format_preset(project_id, preset, style_overrides)`；正文必须已存在（否则 FileNotFoundError 显式报错）。
- Output: 格式化后的正文 docx + `{preset, label, summary}` 结果（写回 document_state 由上游完成）。

## 调用链
- **上游**: `technical_document_service.apply_format`。
- **下游**: `tech_assembly`（延迟 import 复用 `_run_local_tech_format_cleaner` 等）、`onlyoffice_documents.document_path`、`workspace_artifacts`、`workspace_project_access`。

## 中间数据与状态
- technical workspace stage 格式化工作目录；预设常量。
