# technical_gap_actions

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_gap_actions.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 272 |

**职责**: 技术缺口的动作执行层：计划构建入口（委托 planner）、现有素材登记（select-material 落 resolvedArtifacts）、人工上传登记（base64 docx 解码校验）、AI 填写执行入口（委托 ai_fill）。

## Input（输入）
- 项目 dict + gap_id + 动作请求（素材引用 / data-URL base64 docx / AI 填写参数）。

## Output（输出）
- `register_technical_existing_gap_material` / `register_technical_manual_gap_upload`：产物登记（写 workspace 文件 + resolvedArtifacts）→ 终审判 ready。
- `run_technical_ai_fill_for_gap`：AI 填写产物；`build_technical_gap_plan_for_project`：计划构建转发。

## 调用链
- **上游**: `technical_gap_service`。
- **下游**: `technical_gap_planner`（计划）、`technical_gap_ai_fill`（填写，Skill 常量 `TECHNICAL_TABLE_FILL_SKILL_NAME`/`TECHNICAL_WORD_FILL_SKILL_NAME` 转出）、`technical_gap_domain/state`、`technical_material_store`、`minio_client`、`workspace_artifacts`。

## 中间数据与状态
- technical workspace 目录内产物文件；resolvedArtifacts 记录（source=manual_upload/existing_material/ai_fill）。
