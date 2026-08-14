# 阶段命名映射表

用户侧阶段名与历史命令别名/工作目录编号互相错位（历史编号来自旧流水线，后端和产物路径依赖太重，短期不改名）。**本表是唯一映射事实来源**，各 SKILL.md 只引用本表，不要各自另写解释。

命令别名的机器可读事实源是同目录 `commands.json`（harness-09 起容器启动时按它生成 `/usr/local/bin` wrapper）；本表别名列必须与 `commands.json` 一一对应，由 `tests/test_skill_command_registration.py` 强制对齐。

## 技术标

| 用户侧阶段 | Skill | 命令别名 | 历史工作目录 / 文件 |
|---|---|---|---|
| S0/S1 解析 | bid-tech-tender-structured-parser | `s1parse` | `s1_parse_manifest.json` |
| S1 模板与目录 | bid-tech-outline-generator | `s2outline`（兼容 `s2toc`） | `s2_toc_workdir` |
| S3 缺口处理（识别） | bid-tech-gap-planner | `s4gap` | `s4_gap_workdir` |
| S3 缺口处理（空副表填写） | bid-tech-table-filler | `s4fill-prepare` / `s4fill-apply`（LLM 判断为唯一模式） | `s4_gap_workdir/ai_fill/<gapId>` |
| S3 缺口处理（待填写 Word） | bid-tech-word-placeholder-filler | `s4wordfill` | `s4_gap_workdir/ai_fill/<gapId>` |
| S3 缺口处理（事实表维护） | bid-tech-fact-curator | `factcurate` | `s4_gap_workdir/fact_curate` |
| S4 生成标书（正文组装） | bid-tech-assembler | `run_from_manifest.py` | `s7_assembly_workdir` |
| 成稿后处理（格式清洗） | bid-tech-format-cleaner | `run_from_manifest.py` | `s5_format_switch_workdir`（目录 JSON 由 s2 产物转换） |
| 成稿后处理（评分索引交叉引用） | bid-tech-score-index-xref | `xrefindex`（章节判断）+ `run_from_manifest.py`（建引用） | `s7_assembly_workdir/tech_score_index_xref_*.json` |
| 素材库旁路（Wiki 索引） | bid-tech-wiki-material-builder | `run_from_manifest.py` | `_runtime/materials/technical_material_index.json` |

## 商务标

| 用户侧阶段 | Skill | 命令别名 | 历史工作目录 / 文件 |
|---|---|---|---|
| S1 解析 | bid-business-tender-structured-parser | `s1parse`（与技术轨共享路由，按 manifest `parseProfile`/`bidType` 分发） | `business-workspace/parse/s1_parse_manifest.json` |
| S1 解析（商务模板提取） | bid-business-template-extractor | `btplnav` | `business-workspace/parse/business_template_extraction/` |
| S2 目录生成 | bid-business-outline-generator | `business-outline` | `business-workspace/s2_toc_workdir` |
| S3 缺口处理（识别） | bid-business-gap-planner | `businessgap` | `business-workspace/gaps/business_gap_plan.json` |
| S3 缺口处理（表格/附件填写） | bid-business-table-fill | `businesstablefill` | `business-workspace/gaps/table-fill/<taskId>` |
| S4 生成标书（组装） | bid-business-assembler | `businessassemble` | `business-workspace/s4_assembly_workdir` |
| 成稿后处理（格式清洗） | bid-business-format-cleaner | `businessformat`（manifest 为位置参数，无 `--manifest` 旗标） | `business-workspace/s4_format_switch_workdir` |
| 素材库旁路（Wiki 索引） | bid-business-wiki-material-builder | `wikibuild`（与技术轨共享路由，按 manifest `targetBidType` 分发） | `business-workspace/wiki` |

注意事项：

- 用户侧没有 S2 阶段；`s2/s4/s5/s7` 等前缀只是历史工作目录编号，与用户侧 S1/S3/S4 不对应。
- S4 链路顺序固定为：正文组装 → 图表题注编号 → 格式清洗 → 评分索引交叉引用。题注编号是纯规则脚本、不经 agent，所以不是 skill，实现在 `app/document_processing/technical_document/captioning/`，不在本表内。题注必须先于格式清洗（清洗会把素材图名提升成 Heading，题注就改写不到了），交叉引用必须最后（前面每一步都改分页）。
- 后端代码（`app/services/`）与产物路径仍使用历史编号；改动这些名字属于跨线重构，须单独立项评审。
- 素材轨 bid-material-format-cleaner 由后端 worker 直接驱动（`material_cleaning` job），无命令别名，不在两表内。
