# business_document_editing

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_document_editing.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 178 |

**职责**: 商务标正文的「受控改写」执行器：只允许人工确认的单点精确替换——原文必须在正文/表格段落中**唯一匹配**（整段或段内唯一子串），否则拒绝改动；改前先备份。

## Input（输入）
- `apply_controlled_business_rewrite(project_id, original_text, replacement_text, operator)`。

## Output（输出）
- 改写后的正文 docx（documents 卷 `{pid}.docx`）；改前备份到 workspace stage 目录；返回改写记录。多处/零处匹配抛错，不做任何变更（刻意避免宽泛 AI 编辑）。

## 调用链
- **上游**: `business_document_service.apply_rewrite`（`business-rewrite/apply` 端点）。
- **下游**: `onlyoffice_documents.document_path`、`workspace_artifacts.workspace_stage_dir`、`workspace_project_access`、python-docx。

## 中间数据与状态
- 备份文件（workspace stage 目录）；改写模式 `paragraph|literal_substring`。
