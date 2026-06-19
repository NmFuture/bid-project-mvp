# llm-wiki 构建思路 × 商务标 Wiki 对比分析笔记

> 整理日期：2026-06-03
> 对比对象：开源项目 nashsu/llm_wiki  ×  本项目 bid-business-wiki-material-builder skill

---

## 一、llm-wiki 是怎么"构建"的

它的本质不是一个 RAG 检索器，而是一个**让 LLM 持续维护的、可累积的知识库编译器**。
核心可以拆成三层 + 三个操作 + 两个索引文件。

### 三层架构

```
Raw sources（只读、不可变的真相源）
      ↓ LLM 读取、抽取、整合
The Wiki（LLM 全权拥有的 markdown 页面集合，带 [[双链]]）
      ↑ 由
The Schema（schema.md / purpose.md —— 告诉 LLM 该怎么组织，是关键配置）
```

它和普通 RAG 最大的区别：**RAG 每次查询都从零重新发现知识，而 wiki 是"编译一次，持续保鲜"**。
交叉引用、矛盾标记、综合结论都已经预先写进页面里了。

### 三个操作

1. **Ingest（摄入）** —— 整个系统的发动机（src/lib/ingest.ts，约 2600 行）。
   不是简单 chunk+embed，而是一个**两阶段 LLM 管线**：
   - **Stage 1 分析**（buildAnalysisPrompt）：LLM 先读 source，产出结构化分析——关键实体、概念、
     主张证据强度、**与现有 wiki 的连接、矛盾点**。这是"先想再写"。
   - **Stage 2 生成**（buildGenerationPrompt）：LLM 拿着自己的分析，产出 `---FILE: wiki/xxx.md---` 块
     + `---REVIEW:---` 块。一次摄入会触碰 10-15 个页面：source 摘要页、实体页、概念页、index.md、log.md、overview.md。
   - 关键细节：**页面已存在时是 LLM 智能合并**（mergePageContent），不是覆盖——保留所有来源的贡献。

2. **Query（查询）** —— 先读 index.md 定位，再钻进页面综合作答，**好的答案能回写成新页面**（让探索也累积）。

3. **Lint（健康检查）** —— src/lib/lint.ts 检测孤儿页、断链、无出链、矛盾、过时声明。

### 工程上真正硬核的地方（写 skill 时最值得偷的）

- **路径穿越防御**（isSafeIngestPath）：LLM 输出的文件路径可能被 source 里的 prompt injection 污染
  （`---FILE: ../../etc/passwd---`），所以在解析边界强制只允许 wiki/ 下、拒绝 ../绝对路径/Windows 非法名。
- **解析器健壮性**（parseFileBlocks）：处理了 6 类真实失败——CRLF、流截断、大小写/空格变体、
  代码块内的伪 `---END FILE---`、空路径。失败不静默丢弃，而是 warnings 上浮给用户。
- **长文档分块 + 断点续传**（analyzeLongSourceInChunks）：超预算的 source 按语义切块、带 overlap、
  维护"全局 digest"，并把进度写 checkpoint JSON，中断后能 resume。
- **缓存**（checkIngestCache）：source 内容没变就跳过重新摄入。
- **模板即 Schema**（templates.ts）：research/reading/personal/business/general 五套预制 schema，
  每套定义了 page types、命名规则、frontmatter、交叉引用规则、矛盾处理规则。

---

## 二、商务标 Wiki 是怎么构建的

本项目的 bid-business-wiki-material-builder skill 走在一条**比 llm-wiki 更克制、更适合合规场景**的路上。
核心模式是 **"确定性脚本产骨架 + LLM 精修"**：

```
materialInventory.items（后端清洗管线产出的素材清单 = Raw sources）
      ↓ business_wiki_blueprint.py（纯规则，确定性）
固定 5 节点骨架 + 13 模块映射 + 每条素材一张证据卡片
      ↓ LLM 精修（只改判断/描述，绝不改事实）
最终 wiki_blueprint.json
```

与 llm-wiki 的**根本理念差异**：

- llm-wiki 让 **LLM 全权写 wiki**（创意优先，容忍不确定）。
- 本项目让 **脚本兜底事实层，LLM 只在语义层精修**（合规优先，**铁律是绝不编造金额/日期/证书编号**）。
  这是商务标场景的正确选择——已经识别到 issue_date / document_number / issuer 是"正则启发式猜测、
  提示性而非权威"，并保守置 pending_verify。

---

## 三、值得借鉴 llm-wiki 的 7 个思路（按 ROI 排序）

### 立刻能用

**① 引入 log.md 式的"操作时间线"**
现在每次 rebuild 是**全量覆盖**，没有历史。llm-wiki 的 log.md（append-only、`## [YYYY-MM-DD] ingest | Title`
前缀可被 grep 解析）能回答："这次重建比上次多/少了哪些素材？哪张证据卡片是什么时候因为什么变的？"
对商务标的**审计追溯**极有价值。建议在骨架里加第 6 节点或在 05-使用规则 同级加一个 00-变更日志。

**② Lint 健康检查节点**
脚本已经有 needs_human_confirm / pending_verify，但缺一个**全局体检视图**。借鉴 lint.ts，可以在脚本里
加一段统计："映射表中 candidate_card_ids 为空的模块数"、"孤儿证据卡片（没被任何模块引用）"、
"所有 validity_status=expired/pending_verify 的卡片清单"、"high 阻塞待办数"。
这正是下游 Agent 和人工最想先看的"红灯面板"。

**③ 矛盾/冲突显式追踪**
llm-wiki 的 REVIEW: contradiction 机制。商务标的高频矛盾：**同一资质有多个版本、有效期冲突、
客户素材跨客户串味**。现在靠 is_final_version 和优先级规则隐式处理，但没有一个集中的"冲突清单"。
建议在 04-待确认清单 里增加一个 05-证据冲突 分组，脚本自动检测"同 evidence_topic + 同身份范围下
存在多个候选且 validity 不一致"的情况。

### 中长期演进

**④ Schema 与代码解耦（模板化）**
llm-wiki 把 5 套 schema 抽成 templates.ts 的数据，代码只是渲染器。本项目的 13 个 MODULE_CONFIGS、
6 个 COMMON_GROUPS、各种 *_RE 正则和关键词表**全部硬编码在 .py 里**。如果未来要支持"技术标 wiki"或
"不同招标方的模块体系"，现在得改代码。建议把 MODULE_CONFIGS + 分组 + 关键词规则抽到一个
business_schema.json，脚本读它——这样新增一种标书类型就是加一个 JSON。

**⑤ 增量摄入 + 内容指纹缓存**
借鉴 checkIngestCache。现在每次都是从 inventory 全量重算。当素材库有几百条、只新增了 3 条时，
理想是**只为变化的素材重生成卡片**。可以给每条素材算一个内容指纹
（path+cleanedMinioKey+tags+ocr 的 hash），和上一版 blueprint 比对，跳过未变的。

**⑥ 解析器/边界健壮性思维**
LLM 精修阶段会把结果"写回同一个 blueprint JSON"。llm-wiki 在 parseFileBlocks 里对 LLM 输出做了
大量防御。建议给精修结果加一道**确定性校验**：LLM 写回后，用脚本验证
(a) 5 个一级节点没被改动/删除、(b) 没有新增任何 issue_date / document_number 等事实字段相对脚本
输出的差异、(c) card_id 没有重复。把 SKILL.md 里的"铁律"从口头约束变成**可执行的 guard**。

**⑦ 双链导航（可选）**
llm-wiki 用 [[wikilink]] 让证据卡片、模块、待办互相跳转，配合 Obsidian 图视图能看出枢纽和孤岛。
本项目的证据卡片和模块映射现在靠 card_id 字符串关联。如果产物会被人在某个 wiki 系统里浏览，
加双链能显著提升可导航性。但如果纯给下游 Agent 消费，优先级低。

---

## 四、一句话总结

> **llm-wiki 教你"让 LLM 持续编译并保鲜知识、把交叉引用和矛盾预先固化进页面"；
> 本项目的商务标 wiki 在此之上做了关键约束——用确定性脚本守住事实层，让 LLM 只在语义层精修。**

已经做对了最难的一步（事实/判断分离）。从 llm-wiki 最该补的三件事是：
**① log 时间线追溯、② lint 红灯面板、③ 冲突显式清单**——这三个都是"合规可审计"的直接增强，
且都能在现有的纯脚本骨架里实现，不破坏"确定性"这个核心优势。

**推荐落地起点**：② Lint 红灯面板（改动最小：在 build_business_wiki_blueprint 里加一个 build_health_node，
收益最直接）。
