---
name: bid-tech-word-placeholder-filler
description: 技术标 S3 素材库待填写 Word 占位符填写。用于 manifest 已限定待填写 Word 与带清单列的项目事实表，需要保留原 Word 结构、按占位符查表填入、标黄无法确定内容。
allowed-tools: [Read, Bash, Write]
---

# 技术标待填写 Word AI 填写

你是技术标素材库待填写 Word 填写专家。你只能依据 manifest 中已经给定的内容工作：

- `blankSource`：素材库中的 `待填写-*`、`机型固化&待填写-*` 等 Word 模板。
- `projectFactTable`：已确认的项目事实表，字段自带清单第 2 列 `targetFile`（填进哪个 Word）与第 3 列 `placeholder`（占位符原文）。**取值只从这里来。**
- `parseFields`：招标解析阶段抽取的结构化字段。
- `projectTurbineModel`：当前投标机型。

正文填写不读参考素材：定位靠清单、取值靠事实表，素材既不参与定位也不提供取值。
禁止重新搜索全库，禁止读取 manifest 之外的文件。无法确定的占位符必须写入
`[待人工补充：字段名]`，黄色高亮，并列入 `unfilledFields`。

运行边界：

- Agent 只确认 manifest 已给足待填写 Word 和参考范围，并调用一次命令。
- 脚本负责读取 Word、识别段落和表格中的 `[字段，待填写]` / `[待填写：字段]` / `[字段，待补充]` 等占位符，按下面的三级收敛定位字段，替换可确定内容并生成报告。
- 该 Skill 只处理正文/表格单元格占位符；S0 解析出来的空副表仍由 `bid-tech-table-filler` 处理。

## 字段定位：逐级收敛

事实表清单本身就是「字段 → 填进哪个 Word → 占位符长什么样」的路由表，不靠字面相似度反猜字段：

1. **占位符即字段名**：占位符文字归一化后等于字段名或复核列别名时直接命中，零歧义。素材库里多数占位符已经是这个形态（`[单台机组功率曲线保证率（%），待填写]`），实测覆盖约六成。
2. **文件路由（软过滤）**：`targetFile` 按文件名（去路径去扩展名）比对当前 `blankSource`，命中的候选优先；一条都没命中时不做排除——清单文件名与实际待填写文件对不上时，硬过滤会让整份文件静默一个字段都填不进去。
3. **占位符索引**：Word 扫出的占位符与清单 `placeholder` 归一化后查表，唯一命中即确定性填入。
4. **候选内上下文消歧**：同一占位符对多个字段时（清单粒度粗于素材，如 `[技术方案，待填写]` 在塔筒专题对应 58 个字段），用文档上下文区分——表格取行标签与列头，段落取整句，按字段名被上下文片段覆盖的字符位置比例打分；冠亚军差距不足视为分不开。

逐级都定位不到就标黄，不做模糊猜测。清单里没有的占位符直接标黄并计入诊断，不退回全库模糊匹配。

只有带清单元数据（`placeholder` / `targetFile`）的事实表字段进入第 1 级索引。派生事实（招标方、项目名称等）不进：它们的字段名可能恰好等于泛占位符文字（如「投标方案」），会劫持整份文档里该占位符的所有位置。

清单未下发（历史 manifest 无 `projectFactTable`，或字段不带清单元数据）时脚本直接报错退出，
不再退回旧的上下文规则 + 模糊匹配链路——没有定位依据就没有可信取值，静默降级只会产出可疑值。

素材侧的占位符拆得越细，走第 1 级的比例越高，第 4 级自然越少触发，无需改代码。

占位符识别范围：`[xx]` / `【xx】` 括号内容，可带 `待填写：` 前缀或 `，待填写 / 待补充 / 待确认` 后缀（如 `[质保期，待填写]`、`【待填写：交货期】`）。段落和表格单元格都会扫描。

单 manifest 只处理一个 `blankSource`，无批量模式（批量需求由上游 gap-planner 拆成多个 fillTask、逐个下发 manifest）。

输出必须满足：

- Word 写入 manifest 的 `outputFile`。
- JSON schema 为 `bid-tech-word-placeholder-fill-v1`。
- 返回 `outputFile`、`unfilledFields`、`evidenceRefs`、`fillReport`。
- Word 必须保留原文档结构，不能重建说明型 Word。
- 填写依据写入 `outputFile` 同名的 `.fill_report.json` 和 `.fill_report.md`（与 `bid-tech-table-filler` 同一命名约定），含占位符总数/已填/待人工计数。
- 报告另给五张诊断表，供业务侧按黄标数量排优先级拉齐清单：`ambiguousPlaceholders`（该拆细占位符）、`compositePlaceholders`（一格多字段，需产品决策）、`placeholdersNotInSpec`（清单漏字段）、`fieldsWithoutValue`（该补事实表）、`fieldsNotFoundInDoc`（文件填错或占位符改过）。

后端 manifest 调用：

```bash
s4wordfill /data/documents/<projectId>/technical-workspace/s4_gap_workdir/ai_fill/<gapId>/word_fill_input.json
```
