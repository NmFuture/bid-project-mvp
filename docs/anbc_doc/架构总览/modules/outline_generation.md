# outline_generation

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/outline_generation.py` |
| 层级 | 服务层 |
| 领域 | 解析与AI引擎 |
| 行数 | 大型 |

**职责**: 目录（大纲）生成引擎：准备目录 manifest（解析输入件、模板、预算裁剪），按标类选 Skill（技术 `bid-tech-outline-generator`/命令 s2toc；商务 `bid-business-outline-generator`/命令 business-outline），本地规则引擎或经 opencode 执行 Skill 生成目录 JSON。

## Input（输入）
- 项目解析输入件（`project_parse_input_records`）、模板 docx（`template_store.is_valid_docx_file` 校验）、图片走 OCR 兜底（`parsing._ocr_fallback_text`）。
- 审核预算 `OUTLINE_REVIEW_BUDGET`（候选条数/字符数裁剪，控制 prompt 体积）。

## Output（输出）
- 目录 JSON（summary+nodes）→ `bid_outline_state.save_generated_outline_state` 落运行态与 workspace `toc.json`；规则证据（decisions，公开上限 80 条）；opencode 执行轨迹。

## 调用链
- **上游**: `bid_directory_flow`（含 worker 侧 job）。
- **下游**: `opencode_client`、`parsing`（OCR 兜底）、`bid_outline_state`、`template_store`、`workspace_artifacts`、`workspace_project_access`、Skill 脚本 `opencode/skill/*/scripts/run_from_manifest.py`（本地 subprocess 路径）。

## 中间数据与状态
- workspace 内 manifest 与 `toc.json` / `toc_evidence.json`（文件名由 `S2_TOC_OUTPUT_FILE_NAME` 配置）；`directory_state` 事件与轨迹。
