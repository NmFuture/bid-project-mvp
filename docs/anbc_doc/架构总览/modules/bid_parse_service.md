# bid_parse_service

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/bid_parse_service.py` |
| 层级 | 服务层 |
| 领域 | 项目与状态流 |
| 行数 | 大型 |

**职责**: 双轨共用的 S1 解析服务（导出 `business_parse_service` / `technical_parse_service` 两个实例）：上传落盘、异步解析、进度状态、解析资产（附表/承诺函/评分）物化与 OnlyOffice 预览确认。

## Input（输入）
- `upload_and_parse(project_id, tender_files, template_files)`：前端 multipart 上传的招标/模板文件（1MB 分块落盘）。
- 解析画像 `parse_profiles.BUSINESS/TECHNICAL_PARSE_PROFILE` 决定轨道差异。

## Output（输出）
- 解析结果状态（经 `bid_parse_state`：start→progress→complete）；附表 blankDocx / 承诺函 docx 物化文件（`parsing.materialize_*`）；OnlyOffice 编辑会话与回调保存；资产 approve 状态（商务侧经 `business_parse_assets`）。

## 调用链
- **上游**: `routes/business.py`、`routes/technical.py` 的 parse-results 端点组。
- **下游**: `parsing`（真正解析）、`bid_parse_state`、`bid_project_service/state`、`business_parse_assets`、`business_template_extractor`、`onlyoffice_documents`、`workspace_project_access`、`parse_profiles`、`url_utils`。

## 中间数据与状态
- uploads/parsed 数据卷文件；`parse_state`（进度/事件/结果）；OnlyOffice 回调 token 校验（`oo_callback_token`）；编辑会话 key（`build_editor_session_key`）。
