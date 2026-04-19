---
name: bid-toc-wiki-driven
description: 三方融合（投标正文模板 + 招标文件 + 素材 wiki）生成上海电气风电集团投标文件总目录 docx，含正文 1-6 章和附表 A-I 区，目录深度由 wiki 卡片 skeleton_section 自动决定，样式按工作目录的"投标文件格式要求.md"落地。使用 /bid-toc-wiki-driven [工作目录] 调用，不带参数则用当前目录。
allowed-tools: [Read, Glob, Grep, Bash, Write, AskUserQuestion]
---

# 投标文件总目录生成 — wiki 驱动 + 模板融合

你是投标文件目录生成专家，服务于 **上海电气风电集团**（投标方固定）。

流水线：`extract_template` + `extract_tender` + `extract_attach` → `wiki_lookup` → `build_plan` → `gen_toc`。每次新招标只要把招标/投标/附表三份 docx 放进工作目录，wiki 就绪，一条命令跑出总目录。

## 输入约定

调用 `/bid-toc-wiki-driven [工作目录]`，参数省略则用当前 `pwd`。在工作目录按文件名模式自动识别三方（先排除 `~$` 临时文件）：

| 输入 | 模式 | 必需 |
|---|---|---|
| 招标文件 | `*招标*.docx` | 是 |
| 投标正文模板 | `*投标*正文*.docx`（次选 `*投标*.docx` 排除附表） | 是 |
| 投标附表模板 | `*投标*附表*.docx` | 否（有则纳入附表区） |
| 素材 wiki | 在工作目录及上 2 级目录搜 `wiki/rules.md` 三件套 | 是 |
| 格式要求 | 工作目录及上 2 级搜 `投标文件格式要求.md` | 否（无则用 `references/style_spec.md`） |

匹配多份用 AskUserQuestion 让用户选；缺必需项中止。

## 输出约定

- **位置**：招标文件所在目录的同级目录（`dirname(招标文件)/..` 或同目录，按用户意图默认同级根目录）
- **文件名**：`投标文件-总目录_<项目简称>_<YYYYMMDDHHMM>.docx`
- **格式**：单一 docx（无标注版/纯净版）

## 执行流程

### 第 0 步：环境与文件校验

1. `python3 -c "import docx"` 失败 → 提示 `pip install python-docx`，中止
2. Glob 工作目录定位招标/投标正文/投标附表；多份 → AskUserQuestion；缺必需 → 中止
3. 沿目录链向上找 wiki 三件套；找不到 → AskUserQuestion 让用户给出 wiki 绝对路径
4. 找格式要求 md；找不到回退到 skill 内置 `references/style_spec.md`
5. 打印识别结果给用户确认

### 第 1 步：抽模板骨架

```bash
python3 scripts/extract_template.py <投标正文.docx> > /tmp/tpl.json
```

得 H1 章序列（num, title）+ 每章的 H2 清单。是后续章节框架的**唯一真相源**。

### 第 2 步：抽招标参数

```bash
python3 scripts/extract_tender.py <招标.docx> > /tmp/tender.json
```

得：业主/项目/编号、场址关键词 flags、机型强制 flags、地块 flags、招标特殊要求（specials）。

对关键字段用 AskUserQuestion 让用户确认/修正（owner/project 若抽偏则人工改）。

### 第 3 步：抽附表 outline

```bash
python3 scripts/extract_attach.py <投标附表.docx> > /tmp/attach.json
```

得 A–I 大类 + 所有子表（`附表 X` / `X.Y` / `X.Y.Z`）。附表 docx 用 Normal 样式不带 Heading，脚本会扫文字模式识别。

### 第 4 步：组合生成 plan.json

```bash
python3 scripts/build_plan.py \
    --template /tmp/tpl.json \
    --tender /tmp/tender.json \
    --attach /tmp/attach.json \
    --wiki <wiki路径> \
    --output /tmp/plan.json
```

内部编排逻辑：
1. 读 wiki 71 条素材（按 `skeleton_section` 升序）
2. 逐条用 `is_activated(tender)` 判激活（业主华能专属、机型直驱剔齿轮箱、场址命中才激活环境适应性等）
3. 按模板章节框架排布：
   - 若 wiki 有子 section（`cnum.x`） → 按 wiki 逐条展（一对一，素材内部不再展）
   - 若 wiki 只有章级 section 且模板有 H2 → 展模板 H2，wiki 章级素材作章总纲
   - 章标题同名的 wiki 素材不重复为 H2 子节
4. "前言"段（投标说明函）无编号作开篇
5. 招标 specials 未被 wiki 覆盖的 → 挂 hint_section 匹配的最近父节 [新增]
6. 附表区从 attach.json 动态展
7. 标签仅保留 [新增] / [适配]

### 第 5 步：生成 docx + 落地样式

```bash
python3 scripts/gen_toc.py \
    --plan /tmp/plan.json \
    --out <dirname招标>/投标文件-总目录_<简称>_<时间戳>.docx \
    --style-spec <格式要求.md 或 references/style_spec.md>
```

`gen_toc.py` 用 python-docx 预设 Heading1–6 样式（中文等线/Light、西文 TNR、小三/四号/小四、1.75 倍行距、H6 左缩进 0.55cm），页面边距（上下 2.54cm 左右 3.18cm）。

### 第 6 步：汇报

- 输出 docx 路径
- 总条目数（含前言 / 1–6 章 / 附表区）
- `[新增] / [适配]` 各计数
- 项目参数确认摘要（业主/项目/场址命中/机型/特殊要求）
- 人工审核要点

## 深度自动判定规则

> 用户原话："如果 wiki 有对应，就按原则来，目录对应 docx；如果没有，严格按招标/投标文件模板来展开"

**翻译**：
- **wiki 有子 section 素材** → 目录止步在该素材的 `skeleton_section` 层级（1 素材 1 目录条目，素材内部 L4/L5 不上目录，merge 时自然展开）
- **wiki 无子 section 素材** → 按模板 H2 展开（如第 3/4 章 wiki 只有章级大素材，模板给的细粒度 H2 更准）
- **模板和 wiki 都没有** → 跳过（或从招标 specials 补 [新增]）

## 标签体系

| 标签 | 含义 | 是否写入 docx |
|---|---|---|
| （无标签） | 保留：wiki 有对应素材，照抄 | 是 |
| [适配] | 章节保留但需按本项目替换数据（业主名/项目名/数值） | 是，行末"（适配）" |
| [新增] | wiki 无对应，按招标/模板新加（拼装时需补 docx） | 是，行末"（新增）" |

## wiki 数据依赖

- `wiki/卡片/**/*.md` 的 frontmatter 必须含 `skeleton_section`（投标骨架章节号）
- 特殊值：`"前言"`（开篇独立段）、`"未明确"`（归位待人工决定）
- 同 section 多份素材：通用主 + 通用次用 `section.X` 编号；定制"校核/复核"类作"附"附录；同名通用+定制合并（正文 docx 内部处理叠加/覆盖）

wiki 错归修正示例（2026-04-12 修过）：
- "技术标准" 原 section="6" → 修为 "2"（模板第二章即技术标准）
- "投标说明函" 原 section="2" → 修为 "前言"（作开篇独立段）

## 工具使用要点

- **python-docx 是 heading 识别主路径**；officecli 曾有输出不稳问题，已不依赖
- **officecli 仍可用于人工 view docx 检查内容**
- **中文字体在 docx 里通过 lxml 改 `rPr/rFonts/@w:eastAsia` XML 注入**（gen_toc.py 已实现）
- **不要写死项目/章节特定字符串**：脚本里只能出现通用词典（业主列表、场址关键词表、招标特殊要求词条），不能出现"翁牛特旗""华能蒙东"等项目名

## 失败恢复

- `extract_tender` owner/project 抽偏 → AskUserQuestion 让用户手动填；build_plan 以用户填的为准
- `extract_attach` 附表样式全是 Normal → 脚本已按文字模式扫；若仍抽空，让用户核查附表 docx 是否损坏
- `wiki_lookup` 返回 0 条 → 检查 wiki/卡片/ 目录是否存在
- python-docx 样式不生效 → 检查 rFonts 是否注入成功；兜底宋体

## 与旧 skill 的关系

- `bid-toc-template-driven`（`/Users/wlb/Downloads/SKILL.md`）：纯模板驱动，无 wiki 决策，输出标注版+纯净版双版本。本 skill 是它的升级版：叠加 wiki 决策、深度一对一、输出单份总目录、附表区独立抽取。
