# progress.md

> 状态：2026-05-27 历史快照。本文不再作为当前状态、验证基线或 5090 部署依据；当前入口见 [`../README.md`](../README.md)，生产发布见 [`DEPLOY_5090.md`](DEPLOY_5090.md)。

## 1. 当前状态

当时的 3 份文档现已归档：

- [`../docs/archive/20260617-old-docs/代码结构梳理.md`](../docs/archive/20260617-old-docs/代码结构梳理.md)
- [`../docs/archive/20260617-old-docs/需求梳理.md`](../docs/archive/20260617-old-docs/需求梳理.md)
- [`../docs/archive/20260617-old-docs/研发计划.md`](../docs/archive/20260617-old-docs/研发计划.md)

代码主线已经形成技术标和商务标双轨：

```text
技术标入口 -> 技术标页面 -> 技术标 API -> 技术标 service -> 技术标 Skill -> 技术标素材/Wiki -> 技术标文档/共创/下载

商务标入口 -> 商务标页面 -> 商务标 API -> 商务标 service -> 商务标 Skill -> 商务标素材/Wiki -> 商务标文档/共创/下载
```

当前保留的工作重点：

- 先跑通商务标真实样本端到端。
- 商务标和技术标解析页都按“上传解析 -> 人工判断是否参与投标”处理；项目总览只展示已确认参与投标的项目。
- 素材库标签、商务 Wiki、共用业绩库。
- 商务素材匹配、三类处理方式、项目事实表、AI填写。
- 商务正文生成、格式处理和 Word/PDF 导出。
- 后端角色、工作区、项目类型强授权。
- 临时文件、文档工作区、MinIO 对象的项目删除清理和 TTL 策略。

## 2. 本轮文档和命名收口

- 旧文档后续已迁入 `docs/archive/`。
- 当时根 `README.md` 曾使用 3 份文档作为入口。
- 当时的《代码结构梳理》覆盖页面、API、services、OpenCode/Skill、素材库/模板/Wiki 存储范围。
- 技术标解析 Skill 已统一为 `bid-tech-tender-structured-parser`。
- 商务目录 Skill 已统一为 `bid-business-outline-generator`。
- 素材清洗通用 Skill 已统一为 `bid-material-format-cleaner`。
- `bid-tech-format-cleaner/SKILL.md` 已补齐。
- 技术标运行态恢复已支持从项目 workspace 下既有 `toc.json` 恢复目录状态，和商务标行为对齐。
- 商务标/技术标解析入口已去掉“先新建项目”的前端口径：上传解析时后台静默创建临时承载，不参与后删除，参与后再进入正式项目推进；项目列表 API 支持按 `reviewDecision=participate` 过滤。

## 3. 当前验证基线

在 `/Users/wlb/Agent/bid-project/code/sewpg-bid-backend` 下已执行：

```bash
PYTHONPATH=. pytest tests/test_s1parse_router.py tests/test_s1parse_router_script.py tests/test_business_parse_skill_script.py tests/test_parse_pipeline.py::ParsePipelineTests::test_s1parse_skill_script_outputs_same_multifile_structured_contract opencode/skill/bid-tech-format-cleaner/tests/test_tech_format_cleaner.py
```

结果：`12 passed`。

```bash
PYTHONPATH=. pytest tests/test_business_material_library_rules.py -k material_cleaning_uses_short_paths_for_long_names
```

结果：`1 passed, 36 deselected`。

```bash
PYTHONPATH=. pytest tests/test_directory_generation.py
PYTHONPATH=. pytest opencode/skill/bid-business-outline-generator/scripts/test_run_from_manifest.py opencode/skill/bid-business-outline-generator/scripts/test_prepare_history_bid_outline_inputs.py opencode/skill/bid-business-outline-generator/scripts/test_prepare_tender_map_inputs.py opencode/skill/bid-business-outline-generator/scripts/test_resolve_source_text_candidates.py opencode/skill/bid-business-outline-generator/scripts/test_extract_format_children_candidates.py
```

结果：目录生成 `30 passed`；商务目录 Skill 脚本组合 `35 passed`。

```bash
PYTHONPATH=. pytest tests/test_bid_material_scope_services.py -k "runtime_recovery or technical_runtime_can_recover_directory"
git diff --check
```

结果：运行态恢复聚焦组合 `2 passed`；diff 检查通过。

```bash
PYTHONPATH=. pytest tests/test_business_gap_planner.py::BusinessGapPlannerTests::test_business_gap_table_fill_creates_artifact_from_target_and_sources tests/test_business_gap_planner.py::BusinessGapPlannerTests::test_business_gap_table_fill_allows_project_fact_table_only tests/test_bid_material_scope_services.py::test_business_gap_table_fill_stays_in_business_service
```

结果：`3 passed`。

```bash
npx eslint src/workspaces/business/pages/BusinessGapRecognition.jsx src/workspaces/technical/pages/TechnicalGapRecognition.jsx
```

结果：通过。

## 4. 下一步

1. 2026-05-28 王立博整理真实商务标样本和验收清单。
2. 彭维锋并行优化商务标智能解析和目录生成。
3. 安博成继续推进素材清洗和商务 Wiki。
4. 肖雨航基于素材库/Wiki/业绩库做素材匹配、项目事实表和 AI填写。
5. 最后串起正文生成、格式处理和 Word/PDF 导出。

### 2026-05-28 安博成任务 4.1/4.2

已完成 `plan_for_Anbc.md` 中前两项：

- 4.1 原始素材多标签：商务素材上传支持多个标签，编辑素材时可更新/清空标签，后端元数据返回 `tags` 数组。
- 4.2 共用业绩库最小版：新增商务素材区“业绩库”页面和 `/api/business/materials/performance` 接口，支持列表、筛选、新增、编辑、删除、上传 Word、下载 Word。

验证记录：

- `npm run build` 通过；仍有既有的大 chunk 提示。
- `python3 -m py_compile` 覆盖新增/改动后端模块通过。
- 本地 Docker 服务重建后 `fastapi`、`worker`、`web` 正常；`/api/healthz` 返回 ok。
- 原始素材上传冒烟返回 `tags: ["资质", "承诺函"]`，PATCH 更新返回 `tags: ["资质", "报价"]`。
- 业绩库新增、标签/标类筛选、编辑、上传 Word、下载 Word 冒烟通过；冒烟数据已删除。
- in-app browser 已打开 `/workspace/business/materials/performance`，页面和“新增业绩”弹窗可渲染。

### 2026-05-28 安博成任务 4.3/4.4

已继续完成 `plan_for_Anbc.md` 中后两项：

- 4.3 商务素材清洗：`bid-material-format-cleaner` 输出 `cleaning_manifest.json` 结构化清单，后端清洗服务读取并保存清洗结果、来源相对路径、输出相对路径、是否可检索、是否需复核等元数据。
- 4.4 商务 Wiki 生成：商务 Wiki 构建输入保留原始素材标签、固定/其他素材标记、清洗状态、原件 MinIO key 和清洗稿 MinIO key；证据卡片、素材总表和节点标签会写入这些字段，便于后续素材匹配按标签和清洗状态筛选。

验证记录：

- `python3 -m py_compile` 覆盖清洗服务、Wiki 生成服务、清洗 Skill driver、商务 Wiki builder 通过。
- `git diff --check` 通过。
- Docker `fastapi`/`worker` 使用 `--no-deps` 重建成功并健康；`/api/healthz` 返回 ok。
- 在 `fastapi` 容器内用 Excel 冒烟跑 `bid-material-format-cleaner`，成功生成 Word 和 `cleaning_manifest.json`，清单记录 `status=OK`、相对输入/输出路径和 `isUsableForRetrieval=true`。
- 用带 `tags`、`cleanResultStatus`、`sourceMinioKey`、`cleanedMinioKey` 的商务 Wiki manifest 跑 `bid-business-wiki-material-builder`，输出五个一级节点，证据卡片包含标签、原件对象 key、清洗稿对象 key 和清洗状态。
- 一次完整 `docker compose up -d --build fastapi worker` 曾因 Docker Hub 拉取 onlyoffice 镜像鉴权 EOF 失败，随后用 `--no-deps` 成功重建目标服务。

### 2026-05-27 22:43:31 post-commit ec6e6ff

提交摘要：docs: align business bid planning docs

变更文件：

- `"doc/\344\273\243\347\240\201\347\273\223\346\236\204\346\242\263\347\220\206.md"`
- `"doc/\347\240\224\345\217\221\350\256\241\345\210\222.md"`
- `"doc/\351\234\200\346\261\202\346\242\263\347\220\206.md"`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-27 22:53:02 post-commit f29bc78

提交摘要：fix(business-gap): remove manual select handling mode

变更文件：

- `code/sewpg-bid-backend/app/services/business_gap_planning.py`
- `code/sewpg-bid-backend/app/services/business_gap_refresh.py`
- `code/sewpg-bid-backend/app/services/business_gap_service.py`
- `code/sewpg-bid-backend/opencode/skill/bid-business-gap-planner/scripts/run_from_manifest.py`
- `code/sewpg-bid-backend/tests/test_bid_material_scope_services.py`
- `code/sewpg-bid-backend/tests/test_business_gap_planner.py`
- `code/sewpg-bid-frontend/src/workspaces/business/pages/BusinessGapRecognition.jsx`
- `code/sewpg-bid-frontend/src/workspaces/business/pages/BusinessMaterialDB.jsx`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-27 23:31:01 post-commit 1dfe5e9

提交摘要：fix: align parse review flow

变更文件：

- `README.md`
- `code/AGENT.md`
- `code/plan.md`
- `code/progress.md`
- `code/sewpg-bid-backend/README.md`
- `code/sewpg-bid-backend/app/api/routes/business.py`
- `code/sewpg-bid-backend/app/api/routes/technical.py`
- `code/sewpg-bid-backend/app/services/bid_project_service.py`
- `code/sewpg-bid-backend/app/services/bid_project_state.py`
- `code/sewpg-bid-backend/app/services/store.py`
- `code/sewpg-bid-backend/app/services/workspace_project_access.py`
- `code/sewpg-bid-backend/tests/test_bid_material_scope_services.py`
- `code/sewpg-bid-backend/tests/test_project_material_scope.py`
- `code/sewpg-bid-frontend/README.md`
- `"code/sewpg-bid-frontend/docs/10-API\346\216\245\345\217\243\346\200\273\350\247\210\344\270\216\345\245\221\347\272\246\350\257\264\346\230\216.md"`
- `"code/sewpg-bid-frontend/docs/11-API\345\255\227\346\256\265\347\272\247\345\245\221\347\272\246\346\230\216\347\273\206.md"`
- `code/sewpg-bid-frontend/src/workspaces/README.md`
- `code/sewpg-bid-frontend/src/workspaces/business/pages/BusinessProjectList.jsx`
- `code/sewpg-bid-frontend/src/workspaces/business/pages/BusinessTenderReview.jsx`
- `code/sewpg-bid-frontend/src/workspaces/technical/pages/TechnicalProjectList.jsx`
- `code/sewpg-bid-frontend/src/workspaces/technical/pages/TechnicalTenderReview.jsx`
- `"doc/\344\273\243\347\240\201\347\273\223\346\236\204\346\242\263\347\220\206.md"`
- `"doc/\347\240\224\345\217\221\350\256\241\345\210\222.md"`
- `"doc/\351\234\200\346\261\202\346\242\263\347\220\206.md"`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-08-04 11:46:05 post-commit cfe7e78

提交摘要：feat(技术标缺口): S3 页面树状改造与八标签体系

变更文件：

- `code/sewpg-bid-backend/app/api/routes/technical.py`
- `code/sewpg-bid-backend/app/services/technical_gap_actions.py`
- `code/sewpg-bid-backend/app/services/technical_gap_service.py`
- `code/sewpg-bid-backend/opencode/skills/bid-tech-gap-planner/SKILL.md`
- `code/sewpg-bid-backend/opencode/skills/bid-tech-gap-planner/scripts/run_from_manifest.py`
- `code/sewpg-bid-backend/tests/test_technical_gap_covered_child_candidates.py`
- `code/sewpg-bid-backend/tests/test_technical_gap_title_only.py`
- `code/sewpg-bid-frontend/src/api/index.js`
- `code/sewpg-bid-frontend/src/components/ui/Badge.jsx`
- `code/sewpg-bid-frontend/src/workspaces/technical/pages/TechnicalGapRecognition.jsx`
- `code/sewpg-bid-frontend/src/workspaces/technical/pages/technicalGapRecognitionHelpers.js`
- `code/sewpg-bid-frontend/src/workspaces/technical/pages/technicalGapRecognitionHelpers.test.mjs`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-08-04 17:49:45 post-commit 2163119

提交摘要：feat(技术标缺口): 标签体系 v6 与右侧面板交互修正

变更文件：

- `code/sewpg-bid-frontend/src/workspaces/technical/pages/TechnicalGapRecognition.jsx`
- `code/sewpg-bid-frontend/src/workspaces/technical/pages/technicalGapRecognitionHelpers.js`
- `code/sewpg-bid-frontend/src/workspaces/technical/pages/technicalGapRecognitionHelpers.test.mjs`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-08-04 18:08:36 post-commit ad29286

提交摘要：fix(技术标缺口): 树层级改 level 栈、定案模板可见、结构章标注仅留标题

变更文件：

- `code/sewpg-bid-frontend/src/workspaces/technical/pages/TechnicalGapRecognition.jsx`
- `code/sewpg-bid-frontend/src/workspaces/technical/pages/technicalGapRecognitionHelpers.js`
- `code/sewpg-bid-frontend/src/workspaces/technical/pages/technicalGapRecognitionHelpers.test.mjs`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-08-04 18:36:35 post-commit 9b7710e

提交摘要：feat(技术标缺口): 识别直跑纯脚本、展示分诚实化

变更文件：

- `code/sewpg-bid-backend/app/services/technical_gap_planner.py`
- `code/sewpg-bid-backend/opencode/skills/bid-tech-gap-planner/scripts/run_from_manifest.py`
- `code/sewpg-bid-backend/tests/test_onlyoffice_document.py`
- `code/sewpg-bid-backend/tests/test_technical_gap_display_scores.py`
- `code/sewpg-bid-frontend/src/workspaces/technical/pages/TechnicalGapRecognition.jsx`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-08-04 18:49:24 post-commit 1f8c4eb

提交摘要：fix(技术标缺口): 整章模板已选区去重

变更文件：

- `code/sewpg-bid-frontend/src/workspaces/technical/pages/TechnicalGapRecognition.jsx`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-08-05 01:57:07 post-commit 9caca7b

提交摘要：docs(协作规则): 补充本机 Dev 测试环境重置 Skill 用法

变更文件：

- `AGENTS.md`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-08-06 02:11:48 post-commit 7b18e0d

提交摘要：feat(技术标): 正文填写按事实表清单定位字段，不再靠字面相似度猜

变更文件：

- `code/sewpg-bid-backend/app/data/technical_fact_field_specs.json`
- `code/sewpg-bid-backend/app/services/technical_fact_spec_import.py`
- `code/sewpg-bid-backend/app/services/technical_gap_fact_table.py`
- `code/sewpg-bid-backend/opencode/skills/bid-tech-word-placeholder-filler/SKILL.md`
- `code/sewpg-bid-backend/opencode/skills/bid-tech-word-placeholder-filler/scripts/run_from_manifest.py`
- `code/sewpg-bid-backend/tests/test_fact_spec_upload.py`
- `code/sewpg-bid-backend/tests/test_technical_fact_field_specs.py`
- `code/sewpg-bid-backend/tests/test_technical_word_fill_discipline.py`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-08-06 02:36:29 post-commit 68b6c31

提交摘要：fix(技术标): 同一占位符被多个同义字段共用时不再静默取首个

变更文件：

- `code/progress.md`
- `code/sewpg-bid-backend/opencode/skills/bid-tech-word-placeholder-filler/scripts/run_from_manifest.py`
- `code/sewpg-bid-backend/tests/test_technical_word_fill_discipline.py`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-08-06 03:20:56 post-commit 418deb6

提交摘要：feat(技术标): 正文一键填写改后台任务，砍掉 opencode 与 OCR 两层空转

变更文件：

- `code/progress.md`
- `code/sewpg-bid-backend/app/api/routes/technical.py`
- `code/sewpg-bid-backend/app/services/job_queue.py`
- `code/sewpg-bid-backend/app/services/technical_body_fill_job.py`
- `code/sewpg-bid-backend/app/services/technical_gap_ai_fill.py`
- `code/sewpg-bid-backend/app/services/technical_gap_service.py`
- `code/sewpg-bid-backend/app/workers/redis_worker.py`
- `code/sewpg-bid-backend/tests/test_gap_event_loop_safety.py`
- `code/sewpg-bid-backend/tests/test_gap_review_flow.py`
- `code/sewpg-bid-backend/tests/test_technical_body_fill_job.py`
- `code/sewpg-bid-frontend/src/api/index.js`
- `code/sewpg-bid-frontend/src/workspaces/technical/pages/TechnicalGapRecognition.jsx`
- `code/sewpg-bid-frontend/src/workspaces/technical/pages/technicalGapRecognitionHelpers.js`
- `code/sewpg-bid-frontend/src/workspaces/technical/pages/technicalGapRecognitionHelpers.test.mjs`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-08-06 03:37:11 post-commit ae5a50d

提交摘要：fix(技术标): 一键填写提交不再清空页面数据，入口收进「待填写」标签

变更文件：

- `code/progress.md`
- `code/sewpg-bid-frontend/src/workspaces/technical/pages/TechnicalGapRecognition.jsx`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-08-06 03:46:57 post-commit 3923201

提交摘要：fix(技术标): 历史事实表补清单第 2/3 列，正文填写不再误走旧模糊链路

变更文件：

- `code/progress.md`
- `code/sewpg-bid-backend/app/services/technical_gap_ai_fill.py`
- `code/sewpg-bid-backend/tests/test_technical_body_fill_job.py`

验证结果：提交后自动记录，需结合提交前测试记录确认。
