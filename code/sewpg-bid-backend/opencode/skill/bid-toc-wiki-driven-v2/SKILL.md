---
name: bid-toc-wiki-driven-v2
description: 三方融合（投标正文模板 + 招标文件 + 素材 wiki）生成上海电气风电集团投标文件总目录 JSON，含正文 1-6 章、附表 A-I 区，并展开 wiki 卡片素材内部 Heading 树为 JSON 子目录；JSON 顶层包含 document_title/project/source_files/summary/items，条目包含 order/number/title/level/annotation/source/reason/source_refs/material_refs。V2 使用六类 annotation：保留、适配、新增-招标要求、新增-素材库建议、删除建议、素材内置标题。不输出 Word/docx 文件。使用 /bid-toc-wiki-driven-v2 [工作目录] 调用，不带参数则用当前目录。
allowed-tools: [Read, Glob, Grep, Bash, Write, AskUserQuestion]
---

# 投标文件总目录生成 — wiki 驱动 + 模板融合（JSON 输出）

你是投标文件目录生成专家，服务于 **上海电气风电集团**（投标方固定）。

流水线：`extract_template` + `extract_tender` + `extract_attach` → `wiki_lookup` → `build_plan` → JSON 校验/汇报。每次新招标只要把招标/投标/附表三份输入 docx 放进工作目录，wiki 就绪，一条命令跑出最终 JSON 总目录。

> `python-docx` 只用于读取输入 `.docx`（招标文件、投标正文模板、投标附表模板），本 skill 不生成 Word/docx 输出。

## 输入约定

调用 `/bid-toc-wiki-driven-v2 [工作目录]`，参数省略则用当前 `pwd`。在工作目录按文件名模式自动识别三方（先排除 `~$` 临时文件）：

| 输入 | 模式 | 必需 |
|---|---|---|
| 招标文件 | `*招标*.docx` | 是 |
| 投标正文模板 | `*投标*正文*.docx`（次选 `*投标*.docx` 排除附表） | 是 |
| 投标附表模板 | `*投标*附表*.docx` | 否（有则纳入附表区） |
| 素材 wiki | 在工作目录及上 2 级目录搜 `wiki/rules.md` 三件套 | 是 |

匹配多份用 AskUserQuestion 让用户选；缺必需项中止。

### 后端 manifest 调用（bid-project 默认）

在 `bid-project` 中，S2 后端会预先准备工作目录和 `s2_input.json`。收到这类任务时优先走 manifest，不要再 AskUserQuestion。

manifest 字段：

```json
{
  "projectId": "PRJ-0001",
  "projectCode": "业务项目编号或 PRJ-0001",
  "bidType": "技术标",
  "projectIdentity": {
    "projectId": "PRJ-0001",
    "projectCode": "业务项目编号",
    "customerId": "CUST-HUANENG",
    "customerCanonicalName": "华能集团",
    "customerAliases": ["华能", "中国华能"]
  },
  "workDir": "/data/parsed/PRJ-0001/s2_toc_workdir",
  "apiBaseUrl": "http://fastapi:8000",
  "tenderFiles": [{"name": "招标文件.docx", "path": "/data/parsed/PRJ-0001/s2_toc_workdir/招标文件.docx"}],
  "templateFile": "/data/parsed/PRJ-0001/s2_toc_workdir/投标文件-正文.docx",
  "attachFile": "/data/parsed/PRJ-0001/s2_toc_workdir/投标文件-附表.docx",
  "wikiDir": "/data/parsed/PRJ-0001/s2_toc_workdir/wiki",
  "outputFile": "/data/parsed/PRJ-0001/s2_toc_workdir/投标文件-总目录.json"
}
```

标准命令：

```bash
python3 /workspace/.opencode/skills/bid-toc-wiki-driven-v2/scripts/run_from_manifest.py \
  --manifest /data/parsed/<projectId>/s2_toc_workdir/s2_input.json \
  --response summary
```

`run_from_manifest.py` 会：

1. 读取 manifest 中的招标文件、投标正文模板、可选附表模板。
2. 若 `wiki/卡片` 不存在或为空，调用后端 API：`GET /api/materials/wiki?bidType=...`，导出文件系统版 wiki。
   导出后的卡片 frontmatter 会包含 `identity_scope/customer_id/project_id/project_code`，用于按项目身份过滤素材。
3. 执行 `extract_template / extract_tender / extract_attach / build_plan`。
4. 将完整 JSON 写入 `outputFile`。
5. `--response summary` 只向 stdout 打印小型摘要 JSON，包含 `outputFile / summary / itemCount`。

返回给调用方时只输出命令 stdout 中的小型 JSON，不要读取完整 `outputFile`，不要使用 Glob/Read 再打开大 JSON，不要输出 Markdown 代码块或解释文字。完整目录 JSON 由后端根据 `outputFile` 自行读取。

## 输出约定

- **位置**：招标文件所在目录的同级根目录（按用户意图默认同级根目录；不明确时用招标文件同目录）
- **文件名**：`投标文件-总目录_<项目简称>_<YYYYMMDDHHMM>.json`
- **格式**：单一 JSON 文件；`annotation` 使用不带方括号的标签值，下游展示时可自行加 `[]`

推荐结构：

```json
{
  "schema_version": "bid-toc-json-v1",
  "document_title": "xxx投标文件总目录",
  "project": {
    "owner": "...",
    "name": "...",
    "code": "...",
    "site_flags": {},
    "model_flags": {},
    "plot_flags": {},
    "specials": []
  },
  "source_files": {
    "template": "...",
    "tender": "...",
    "attach": "...",
    "wiki": "..."
  },
  "summary": {
    "total_items": 0,
    "annotation_counts": {
      "保留": 0,
      "适配": 0,
      "新增-招标要求": 0,
      "新增-素材库建议": 0,
      "删除建议": 0,
      "素材内置标题": 0
    }
  },
  "items": [
    {
      "order": 1,
      "number": "1.1",
      "title": "技术评分标准索引表",
      "level": 2,
      "annotation": "适配",
      "source": "template",
      "reason": "匹配素材库：技术评分标准索引表",
      "source_refs": [{"type": "template", "raw_text": "1.1 技术评分标准索引表\t4", "page": "4"}],
      "material_refs": [{"id": "RAW-0004", "docx": "通用素材/技术标/技术标-技术评分标准索引表.docx", "usage": "both"}]
    }
  ]
}
```

## 执行流程

### 第 0 步：环境与文件校验

1. 使用工作目录已有 venv；若不存在则先创建 venv。下方命令中的 `$PY` 均指向 venv Python（Windows 通常为 `./venv/Scripts/python.exe`）。
2. `$PY -c "import docx"` 失败 → 提示在 venv 中安装 `python-docx`，中止。
3. Glob 工作目录定位招标/投标正文/投标附表；多份 → AskUserQuestion；缺必需 → 中止。
4. 沿目录链向上找 wiki 三件套；找不到 → AskUserQuestion 让用户给出 wiki 绝对路径。
5. 打印识别结果给用户确认。

### 第 1 步：抽模板骨架

```bash
$PY scripts/extract_template.py <投标正文.docx> > /tmp/tpl.json
```

得 H1 章序列（num, title）+ 每章的 H2 清单。是后续章节框架的**唯一真相源**。

### 第 2 步：抽招标参数

```bash
$PY scripts/extract_tender.py <招标.docx> > /tmp/tender.json
```

得：业主/项目/编号、场址关键词 flags、机型强制 flags、地块 flags、招标特殊要求（specials）。

对关键字段用 AskUserQuestion 让用户确认/修正（owner/project 若抽偏则人工改）。

### 第 3 步：抽附表 outline

```bash
$PY scripts/extract_attach.py <投标附表.docx> > /tmp/attach.json
```

得 A–I 大类 + 所有子表（`附表 X` / `X.Y` / `X.Y.Z`）。附表 docx 用 Normal 样式不带 Heading，脚本会扫文字模式识别。

### 第 4 步：组合生成最终 JSON

```bash
$PY scripts/build_plan.py \
    --template /tmp/tpl.json \
    --tender /tmp/tender.json \
    --attach /tmp/attach.json \
    --wiki <wiki路径> \
    --output <输出目录>/投标文件-总目录_<简称>_<时间戳>.json
```

内部编排逻辑：
1. 读 wiki 素材（按 `skeleton_section` 升序）。
2. 逐条用 `is_activated(tender)` 判激活（业主专属、机型直驱剔齿轮箱、场址命中才激活环境适应性等）。
3. 按模板章节框架排布：
   - 模板 TOC / Heading 是主骨架，优先展开模板 H1/H2。
   - Wiki 素材若与模板 H2 同名，挂到该 H2 的 `material_refs`，不重复生成子节。
   - Wiki 素材若挂在已有 H2 下但模板没有对应小标题，作为该 H2 的子目录补充。
   - Wiki 素材卡片含内部 Heading 树时，同步展开为该素材下的 JSON 子目录。
4. “前言”段（投标说明函）无编号作开篇。
5. 招标 specials 未被 wiki 覆盖的 → 挂 hint_section 匹配的最近父节，`annotation="新增-招标要求"`。
6. wiki/rules 判定应出现但模板缺失的活跃素材 → `annotation="新增-素材库建议"`。
7. wiki/rules 判定不适用的模板/wiki 条目 → 不物理删除，保留为 `annotation="删除建议"`。
8. wiki 卡片含素材内部 Heading 树时 → 逐级展开为 JSON 子目录，`annotation="素材内置标题"`、`source="internal_heading"`。
9. 每个条目输出 `order/number/title/level/annotation/source/reason`，并尽量补充 `source_refs/material_refs`。

### 第 5 步：JSON 校验

生成后加载 JSON 并检查：
- 顶层包含 `schema_version`、`document_title`、`project`、`source_files`、`summary`、`items`。
- 每个 `items[]` 至少包含 `title`、`level`、`annotation`。
- 不再出现旧字段 `text`、`tag`。
- `summary.total_items == len(items)`。
- 六类 `annotation_counts` 与实际条目统计一致。

### 第 6 步：汇报

- 输出 JSON 路径
- 总条目数（含前言 / 1–6 章 / 附表区 / 素材内置标题子目录）
- 六类标签计数：`保留` / `适配` / `新增-招标要求` / `新增-素材库建议` / `删除建议` / `素材内置标题`
- 项目参数确认摘要（业主/项目/场址命中/机型/特殊要求）
- 人工审核要点，重点审核 `新增-*`、`删除建议` 和 `适配` 条目

## 深度自动判定规则

> 原则：投标模板是主骨架；招标文件负责删改补；wiki 负责把素材和小标题挂到模板章节下。

- **wiki 与模板 H2 同名** → 模板 H2 保留，素材写入 `material_refs`。
- **wiki 有模板未覆盖的小标题** → 作为模板 H2 下的新增子目录，标为 `新增-素材库建议`。
- **wiki 无子 section 素材** → 按模板 H2 展开。
- **模板和 wiki 都没有** → 跳过（或从招标 specials 补 `新增-招标要求`）。

## 标签体系（V2 六类 annotation）

V2 输出必须让所有目录条目落入以下六类之一。JSON 中 `annotation` 存不带方括号的值；如需显示成 `[适配]`，由下游渲染层处理。

| annotation 值 | 含义 | 典型场景 | JSON 表达 |
|---|---|---|---|
| `保留` | 模板/wiki 章节直接沿用，不需要调整 | 通用必备章节、上海电气特色章节，且与本项目环境/机型兼容 | `"annotation": "保留"` |
| `适配` | 章节保留，但内容后续要改 | 招标方名称替换；项目名称/编号出现在标题里；业绩数据、承诺值更新 | `"annotation": "适配"` |
| `新增-招标要求` | 招标文件明确要求，但模板和 wiki 素材库都没覆盖到，需要补加 | tender specials 命中，且现有 wiki 条目未覆盖 | `"source": "tender_special"`，`reason` 写命中关键词 |
| `新增-素材库建议` | wiki 的 rules.md 判定“这次投标应该有”，但模板缺失，所以建议新增 | 低温场址触发“抗低温设计”等规则驱动条目 | `"source": "wiki"` |
| `删除建议` | 建议删掉，但不物理删除，保留给人工审核 | 非目标业主专属内容；非沿海项目的防盐雾；直驱机型的齿轮箱专题 | `reason` 写删除建议原因 |
| `素材内置标题` | 素材卡片内部自带的 Heading，需进入 JSON 总目录作为子目录 | wiki 卡片 Merge 信息中的素材内部 Heading 树，如 L4/L5 标题 | `"source": "internal_heading"`，`number` 按父条目继续编号 |

## wiki 数据依赖

- `wiki/卡片/**/*.md` 的 frontmatter 必须含 `skeleton_section`（投标骨架章节号）。
- 新版 Wiki 是 AI 检索规则库，不是人工文件夹；卡片 frontmatter / Merge 信息必须尽量包含：
  - `identity_scope`: `general` / `customer` / `project`
  - `customer_id`、`customer_name`、`customer_aliases`
  - `project_id`、`project_code`
- 目录生成只允许读取身份命中的素材：
  - `general` 通用素材总是可读。
  - `customer` 客户素材必须命中 manifest.projectIdentity 的 `customerId` 或客户同义词。
  - `project` 项目素材必须命中 manifest.projectIdentity 的 `projectId` 或 `projectCode`。
- 特殊值：`"前言"`（开篇独立段）、`"未明确"`（归位待人工决定）。
- 同 section 多份素材：通用主 + 通用次用 `section.X` 编号；定制“校核/复核”类作“附”附录；同名通用+定制合并（正文素材内部处理叠加/覆盖）。

wiki 错归修正示例（2026-04-12 修过）：
- “技术标准” 原 section=`"6"` → 修为 `"2"`（模板第二章即技术标准）。
- “投标说明函” 原 section=`"2"` → 修为 `"前言"`（作开篇独立段）。

## 工具使用要点

- `python-docx` 是输入文件 Heading/段落识别主路径；不要依赖 officecli 作为主流程。
- 不要写死项目/章节特定字符串：脚本里只能出现通用词典（业主列表、场址关键词表、招标特殊要求词条），不能出现“翁牛特旗”“华能蒙东”等项目名。

## 失败恢复

- `extract_tender` owner/project 抽偏 → AskUserQuestion 让用户手动填；build_plan 以用户填的为准。
- `extract_attach` 附表样式全是 Normal → 脚本已按文字模式扫；若仍抽空，让用户核查附表 docx 是否损坏。
- `wiki_lookup` 返回 0 条 → 检查 wiki/卡片/ 目录是否存在。
- JSON 校验失败 → 优先修 `build_plan.py` 的输出 schema，不要加兼容旧字段。

## 与旧 skill 的关系

- `bid-outline-json`：旧 S2 轻量 prompt 目录 skill，已下线删除。
- `bid-toc-wiki-driven`：旧 V1 文件目录 skill，已下线删除。
- 本 skill 是当前 S2 唯一目录生成入口：叠加 wiki 决策、深度一对一、输出单份 JSON 总目录、附表区独立抽取。
