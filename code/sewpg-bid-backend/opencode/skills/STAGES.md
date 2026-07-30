# 阶段命名映射表（技术标）

用户侧阶段名与历史命令别名/工作目录编号互相错位（历史编号来自旧流水线，后端和产物路径依赖太重，短期不改名）。**本表是唯一映射事实来源**，各 SKILL.md 只引用本表，不要各自另写解释。

| 用户侧阶段 | Skill | 命令别名 | 历史工作目录 / 文件 |
|---|---|---|---|
| S0/S1 解析 | bid-tech-tender-structured-parser | `s1parse` | `s1_parse_manifest.json` |
| S1 模板与目录 | bid-tech-outline-generator | `s2outline`（兼容 `s2toc`） | `s2_toc_workdir` |
| S3 缺口处理（识别） | bid-tech-gap-planner | `s4gap` | `s4_gap_workdir` |
| S3 缺口处理（空副表填写） | bid-tech-table-filler | `s4fill` | `s4_gap_workdir/ai_fill/<gapId>` |
| S3 缺口处理（待填写 Word） | bid-tech-word-placeholder-filler | `s4wordfill` | `s4_gap_workdir/ai_fill/<gapId>` |
| S3 缺口处理（事实表维护） | bid-tech-fact-curator | `factcurate` | `s4_gap_workdir/fact_curate` |
| S4 生成标书（正文组装） | bid-tech-assembler | `run_from_manifest.py` | `s7_assembly_workdir` |
| 成稿后处理（格式清洗） | bid-tech-format-cleaner | `run_from_manifest.py` | `s5_format_switch_workdir`（目录 JSON 由 s2 产物转换） |
| 素材库旁路（Wiki 索引） | bid-tech-wiki-material-builder | `run_from_manifest.py` | `_runtime/materials/technical_material_index.json` |
| 素材库旁路（标签匹配） | bid-tech-tag-importer | 后端直接投喂 manifest | — |

注意事项：

- 用户侧没有 S2 阶段；`s2/s4/s5/s7` 等前缀只是历史工作目录编号，与用户侧 S1/S3/S4 不对应。
- 后端代码（`app/services/`）与产物路径仍使用历史编号；改动这些名字属于跨线重构，须单独立项评审。
- 商务标（bid-business-*）如需同样映射，在本文件追加第二张表。
