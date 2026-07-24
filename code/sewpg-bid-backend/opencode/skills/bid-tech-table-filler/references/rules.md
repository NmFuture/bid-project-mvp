# 空副表填写规则细则

本文件是 `SKILL.md` 行为规则的展开说明，供需要理解或修改填写行为时查阅。行为的最终事实来源是 `scripts/run_from_manifest.py`（下称 runner），本文按 runner 的实际实现整理，注明关键函数便于回查。

## 1. 填写边界：S1 越界表剔除

S1 解析切分附表时系统性"错位一格"：每张附表 docx 末尾会带上**下一张附表的标题段和第一张表**。填写时必须剔除：

- 判据自包含（`own_table_limit`，runner:729）：blankDocx 内第二个**编号不同的**附表标题（或"附件"标题）之后的表格，全部视为越界内容，不作为填写目标。
- 同编号重复标题是**真续表**，不算边界；边界之内的多张表全部纳入字段识别与填写（`AppendixSpec.own_tables`）。
- 同一判据也用于金标评分（`eval_fill_vs_golden.py` v3 起），保证填写与评分口径一致。

## 2. C.1 / C.2 / C.3 增强词典与专题规则

附表 C.1（总体技术参数）、C.2/C.3（部件参数）使用增强概念词典做字段对齐（`C1_CONCEPTS` / `C2_C3_CONCEPTS`，runner:57/101）：每个概念挂多个同义标签（如 `额定功率` = 单机容量/机组额定功率/单机功率），先按概念对齐再取值。

伴随的专题守门规则（均来自金标反评教训，改动前先跑评估）：

- 数值尾部星号/脚注不是值的一部分（如 `10.7*` → `10.7`，`normalize_value_for_field`）。
- 扫风面积可按 π(D/2)² 纯几何派生；但**总扫风面积与单位千瓦扫风面积量纲差四个数量级，不得互相顶替**（`score`，runner:2218）。
- 场址空气密度取值有专门放行判据（`site_air_density_allowed`），不允许拿标准空气密度冒充。

这些词典按**业主固定附表模板的结构特征**建立（见 AGENTS.md 硬编码边界），不针对单个项目样本。

## 3. 其他附表的通用链路

非 C.1/C.2/C.3 附表走通用链路：主题识别（`detect_appendix_spec`）→ 字段名相似度（`generic_match_score`）→ 解析字段/项目事实/参考素材抽取候选（`collect_facts`）→ 字段映射（`map_fields`）→ 写回原 Word（`fill_doc`）。

部分附表有专用重组器（按标题识别，均在 runner 内）：报价类 B 表、塔架技术参数（附表 C.6）、发货计划、大部件运输、功率曲线矩阵、载荷风参等。这些重组器只在标题命中时启用，不影响通用链路。

## 4. 自动选材

没有人工指定参考素材、也没有 Excel 梳理表路由时，runner 按目标副表标题/字段/占位标签从 `materialIndex` 打分选材（`score_material_candidate`）：

- 优先级：人工指定 `selectedReferenceMaterials` > Excel 梳理表建议 > `materialIndex` 自动打分 > `recommendedMaterials` 兜底提示（不能当最终依据）。
- 选材证据写入报告的 `sourceSelection` 字段，可回查每个来源为什么被选中。

## 5. 批量语义

- 单 manifest 可填一个目标（`blankSource`/`appendixTask`），也可批量（`targets`/`appendixTargets`/`appendixTasks`，`run_batch_manifest`）。
- 批量时每个目标各自产出一个保留原结构的 Word 与子报告，汇总为批量 JSON 报告（`outputFiles` + `targetResults`）。
- 解析出的"副表"只有标题页、没有表格时：原样复制该 Word，报告记 `targetFieldCount=0`，不中断批量任务。

## 6. 评估（golden eval）

对拿到真实中标技术附表的项目，可跑金标逐格评分验证填写质量：

```bash
python scripts/eval_fill_vs_golden.py <fill_results.json> <真实中标技术附表.docx> [report.json]
```

- `fill_results.json` 每条：`{appendixId, number, title, blankDocx, outputFile}`。
- 对齐口径 v4：剔除 S1 越界表 + 行键序列对齐（消除投标人增删行造成的错位假阴性）。
- 正式标书留在本地，**不入库**；基线报告用于对比改动前后的得分涨跌，改动词典/评分规则前后各跑一次。
