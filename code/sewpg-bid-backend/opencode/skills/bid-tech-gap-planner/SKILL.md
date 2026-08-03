---
name: bid-tech-gap-planner
description: 技术标目录确认后缺口识别。输入已确认目录 JSON、招标解析结构化结果、项目/客户/通用素材边界、Wiki 索引和投标机型，输出 bid-tech-gap-plan-v1 识别计划 JSON。
allowed-tools: [Read, Bash, Write]
---

# 技术标缺口识别与处理计划

你是技术标缺口识别专家。你的任务不是生成正文 Word，也不是执行 AI 填写或完整性复查，而是在目录审核后判断每个目录项是否已有可用素材、是否需要填写空副表/Word、是否完全缺失，并输出可审核、可补料、可供后续步骤消费的第一步识别计划。

## 铁律

缺口识别必须以 S2 审核确认目录为全集。不要只输出有匹配素材的目录项，不要只输出有问题的目录项，不要抽样，不要总结成少数章节。`gap_plan.items.length` 必须等于 `tocJsonPath.items.length`，并且顺序一致。若无法满足，命令必须失败，不能输出部分结果。

后端 manifest 调用：

```bash
s4gap /data/documents/<projectId>/technical-workspace/s4_gap_workdir/s4_gap_input.json
```

`s4gap` 和 `s4_gap_workdir` 是历史内部名，用户侧阶段是 `S3 缺口处理`；完整映射见 `../STAGES.md`。

## 输入边界

只使用 manifest 给出的输入，不要自行扩大素材范围：

- `tocJsonPath`: S2/S3 已审核确认的目录 JSON。
- `parseResultPath`: S0/S1 招标解析结果，包含解析生成的空副表/Word。
- `wikiDir`: 当前项目的技术标 Wiki 副本。
- `materialScope`: 允许读取的素材边界，通常只包含技术标通用素材、该客户素材、该项目素材。
- `materialIndex`: 已按 `materialScope` 和投标机型预过滤的素材索引。
- `projectTurbineModel`: 已确认投标机型，用于判断素材是否适配。

不得跨项目、跨客户、跨标段读取素材。`tocJsonPath` 或 `wikiDir` 中的引用只能作为线索，必须能回到 manifest 的 `materialIndex` 或当前测试 manifest 明确给出的目录素材；不能因为旧目录引用就越过 `materialScope`。

## 输出结构

输出必须是 JSON，schema 为 `bid-tech-gap-plan-v1`。每个目录项至少包含：

- `id`、`number`、`title`、`level`
- `status`: `matched` / `missing` / `needs_input` / `resolved` / `ignored` / `structural`
- `decision`: `ready` / `fill_required` / `material_required` / `review_required`
- `usage`: `chapter_master` / `chapter_fill` / `covered_by_parent` / `section_merge` / `appendix_fill` / `structural`
- `coverageRole`
- `coveredByParent`
- `matchedMaterials`
- `candidateMaterials`
- `appendixTasks`
- `requiredInputs`
- `fillTasks`
- `resolvedArtifacts`
- `reviewNotes`
- `materialScope`
- `projectTurbineModel`
- `turbineCheck`
- `nextActions`
- `evidenceRefs`

第一步识别输出必须保持纯净：

- `resolvedArtifacts` 必须为空。
- `fillTasks[].status` 必须是 `pending`。
- 不要写入 AI 填写产物、人工上传产物或复查报告。
- `integrity.coverageStatus` 必须是 `passed`，`integrity.expectedTocItems` 必须等于 `integrity.actualPlanItems`。

## 判断规则

1. 一条目录项最多只能有一份最终匹配素材：`matchedMaterials.length <= 1`。
2. 多个可能素材不能都放进 `matchedMaterials`；最终选中一份放 `matchedMaterials`，其他只放 `candidateMaterials`。
3. 空副表/Word 填写参考素材不能占用最终匹配素材；它们应放在 `appendixTasks[].recommendedMaterials` 或 `candidateMaterials`。
4. 结构性父目录如果只是目录骨架，不需要素材时标记 `decision=ready`、`usage=structural`。
5. 父章目录必须先尝试匹配整章 Word。若父章标题与允许范围内素材名/路径/cleanedFileName 匹配，例如 `项目技术承诺函`、`产品交付、考核及验收`，父章应作为 `coverageRole=chapter_master`，子节作为 `coverageRole=covered_by_parent`，不要把子节误判成缺素材。
6. 有可直接合并正文素材时标记 `decision=ready`，并在 `nextActions` 放 `s4_merge_material`。
7. 整章 Word 如果是待填写模板，父章标记 `decision=fill_required`、`status=needs_input`、`usage=chapter_fill`，子节继承 `decision=fill_required`、`usage=covered_by_parent`，但子节不重复创建填写任务，并创建 `bid-tech-word-placeholder-filler` 的 `fillTasks`。
8. 文件名、素材索引或 Word 正文显示 `待填写` / `待补充` / `待确认` / `placeholderCount>0` 的素材不是可直接合并素材；应标记 `decision=fill_required`、`status=needs_input`、`usage=section_fill`，把该素材放入 `fillTasks[].blankSource` 作为填写前 Word，并使用 `bid-tech-word-placeholder-filler`。
9. 解析阶段已生成空副表/Word，且当前目录项对应附表时，标记 `decision=fill_required`、`status=needs_input`、`usage=appendix_fill`，并创建 `bid-tech-table-filler` 的 `fillTasks`。
10. 找不到可用素材也无法通过空表填写处理时，标记 `decision=material_required`，要求上传或选择素材。
11. 如果投标机型明显冲突，必须进入 `review_required` 或在 `turbineCheck` 中标出冲突，不能直接合并。

## 通用整章素材规则

父章整章素材识别必须泛化，不能写死第几章或某个业务专题：

- 对任意父章，先从 `materialIndex`、已审核目录引用和 Wiki 线索中寻找整章 Word。
- 用父章标题、子节标题、素材 `name/path/folderPath/cleanedFileName` 综合判断，而不是按固定章节号判断。
- 如果素材文件名或清洗文件名能覆盖父章标题，例如 `风资源评估与机位排布方案`、`项目技术承诺函`、`产品交付、考核及验收`，优先作为整章候选。
- 如果父章标题不完全出现在文件名中，但至少多个子节标题能被同一份素材解释，也可以作为整章候选。
- 父章选中一份整章 Word 后，父章标记 `coverageRole=chapter_master`；所有子节标记 `coverageRole=covered_by_parent`、`coveredByParent=<父章 gap id>`。
- 子节不要重复挂同一份整章素材，`matchedMaterials` 必须为空，避免一个目录项对应多份或重复素材。
- 整章素材若是待填写模板，父章使用 `usage=chapter_fill` 并创建一个填写任务；子节继承 `fill_required`，但不重复创建填写任务。

## 空副表规则

招标解析生成的空副表/Word 是 S3 的填写任务来源：

- 附表编号或空表目录项应作为 `fill_required`，不应被相似父章整章素材吞并。
- 附表推荐素材可以使用相似整章素材作为填写参考，但只能出现在推荐/候选列表。
- 每个 `appendixTask` 应包含空表来源、字段/行数信息、推荐素材和后续填写 Skill。

## 甲方已填附表（技术附表输入文件）

项目定制目录下的 `技术附表输入文件/` 是甲方已填写完成附表的约定目录（业主侧固定结构约定）：

- 该目录素材不进正文匹配池，只参与附表查表替换，避免按标题打分误挂到正文章节。
- 查表键严格按命名：文件 `附表C.8 …` 精确覆盖 C.8；`附表G.3 …` 覆盖 G.3 组全部子表（G.3.1/G.3.2/…）；`技术附H …`（含无「表」写法）覆盖 H 组全部。精确编号优先于组前缀。
- 同编号/同字母命中多个不同文件时不自动定案，保持 `fill_required` 由人工选择。
- 目录项附表全部被覆盖时：对应 `appendixTask.sourceRouting.status=client_provided`，不产生 `fillTasks`，写入非 ai_fill 的 `resolvedArtifacts`（`source=client_appendix_input`、`s7Ready`、带 `materialId`），经终审 recompute 判 `decision=ready`、`status=resolved`，S7 装配直接取甲方文件；部分覆盖时只标记已覆盖任务，目录项维持 `fill_required`。

## 运行方式

收到后端 prompt 时，直接调用一次：

```bash
s4gap <manifest>
```

不要先 `pwd/ls/cat`，不要改写 manifest 路径，不要输出解释文字或 Markdown。命令会把完整 `gap_plan.json` 写到 manifest 的 `outputFile`，stdout 只打印小型摘要 JSON。

stdout 必须包含 `tocItemCount`、`itemCount`、`coverageStatus`。正常情况下 `tocItemCount == itemCount` 且 `coverageStatus == "passed"`。如果不是，视为本次缺口识别失败。

## 评估（golden eval）

对拿到正式中标技术卷的项目，可用金标反评基线验证路由决策质量：

```bash
python scripts/eval_golden_baseline.py \
    --answer-docx <技术卷.docx> --answer-docx <技术附表.docx> \
    --gaps gaps.json --manifest s4_gap_input.json --out report.json
```

产出逐项对照行、分类计数和路由一致率。正式标书留在本地，不入库；修改判断规则前后各跑一次，看一致率涨跌，歧义项需人工复核。
