---
name: bid-tech-assembler
description: 阶段 3 投标文件正文组装。输入 S2 目录 JSON（兼容目录 docx）+ wiki + 当前素材库导出的 Word 文件 + 项目参数，输出正文 docx，质量看齐 投标文件-正文.docx 样例。只管正文，不管附表 A–I。使用 /bid-tech-assembler [工作目录] 或 backend manifest 调用。**一把出**：不中途询问用户，所有缺失项写占位符 `[待填写：xx]`，需人工确认的全部汇总到 `needs_review.md`。
allowed-tools: [Read, Glob, Grep, Bash, Write, Edit]
---

# 投标文件正文组装 — wiki 驱动 + 母版起稿（方案 B：文本前缀编号）

你是投标文件正文组装专家，服务于**上海电气风电集团**（投标方固定）。

## 方案 B 核心原则

- **Heading text 直接带章节号字符串**（"第一章  标前概述" / "1.1  xxx" / "5.8.1  xxx"），不依赖 Word 多级列表自动编号
- **母版 Heading 1-6 样式已解绑 numId**（由 tools/clean_master_numbering.py 保证）
- 素材 docx 预处理时剥 `w:numPr`；最终 Word 导航 Heading **只来自 S2 目录**。素材内部 Heading 若能匹配当前父章节下的 S2 子目录，则改写为该 S2 编号 Heading；其余素材内部 Heading 降级为正文小标题并清除段落级 `w:outlineLvl`
- 素材首 Heading 若文本匹配 toc 标题，**物理去重**（避免相邻重复）；不在 S2 目录内的素材内部 Heading 不进入左侧导航/TOC
- 前言段 text="前言  投标说明函"，Heading 1 样式但无章节号前缀
- **封面**作为 skeleton_section="封面" 的 L0 条目，attach_mode=cover，置于文档最前

流水线：`parse_toc`（优先读 S2 JSON）+ `init_params` → `build_assembly`（plan 首位插 COVER） → `merger`（docxcompose + 素材 Heading 对齐 S2/降级）→ `finalize`（TOC 域插于封面后、首 Heading 前）→ `verify`（硬性检查：幽灵章节=0 / 非法 H1=0 / 相邻重复=0）。

## 与 bid-toc-wiki-driven 的关系

| 阶段 | skill | 输出 |
|---|---|---|
| 1 | bid-toc-wiki-driven | 投标目录 JSON |
| 2 | wiki（被动） | 素材检索与规则承载 |
| 3 | **bid-tech-assembler（本 skill）** | 投标文件正文 docx |

**解耦**：阶段 3 只认 S2 的最终目录结果，优先读取当前系统的 `bid-toc-json-v1` JSON；仍兼容历史目录 docx。

## 输入约定

调用 `/bid-tech-assembler [工作目录]`，参数省略则用当前 `pwd`。

| 输入 | 模式 | 必需 |
|---|---|---|
| 目录 JSON / docx | manifest 中的 `tocJsonPath`，或工作目录中的目录 JSON / 历史目录 docx | 是 |
| wiki | `wiki/rules.md` 三件套 + `wiki/卡片/*.md` | 是 |
| 素材库 | 后端从当前素材库导出的 `素材库/投标资料库-通用/` + `素材库/投标资料库-定制/` | 是 |
| 格式要求 | `投标文件格式要求.md`（或回退到 `references/style_spec.md`） | 否 |
| 技术标母版 | `templates/技术投标母版模板.docx` | 否（首次自动生成） |
| 项目参数 | `<工作目录>/project_params.json` | 否（首次由 init_params 生成） |

**非交互策略**：多份匹配自动选 mtime 最新那份，其它候选记入 `needs_review.md`；缺失 wiki 等必需项才中止（占位符无法兜底结构性缺失）。

## 输出约定

- **位置**：工作目录下
- **文件名**：`投标文件-正文_<项目简称>_<YYYYMMDDHHMM>.docx`
- **附带**：`assembly_report.md`（对账报告）+ `needs_review.md`（人工补齐清单）

## 执行流程

### 第 0 步：环境与文件校验（无交互）

1. `python3 -c "import docx, lxml, docxcompose"` 失败 → 提示 `pip install python-docx lxml docxcompose`，中止
2. 后端 manifest 优先传入 S2 的目录 JSON；无 manifest 时 Glob 工作目录定位目录 JSON/docx，多份 → **自动选 mtime 最新**，其它候选写入 `needs_review.md` 的"候选冲突"段
3. 沿目录链向上找 wiki 三件套；找不到 → **中止**（wiki 是结构性必需，不可占位）
4. 定位素材库根（`素材库/投标资料库-通用/` + `/投标资料库-定制/`）；找不到中止
5. 搜 `投标文件格式要求.md`；无则用 `references/style_spec.md`
6. 检查 `templates/技术投标母版模板.docx`；不存在 → `python3 tools/create_tech_master.py`
7. stderr 打印识别结果（仅日志，不等确认）

### 第 1 步：解析目录 JSON / docx

```bash
python3 scripts/parse_toc.py <S2 目录 JSON 或目录 docx> > /tmp/toc.json
```

输出每条 `{idx, level, chapter_no, title, tag, is_preface}`。跳过首行（含"总目录"）。

### 第 2 步：初始化项目参数（无交互）

```bash
python3 scripts/init_params.py \
    --toc <S2 目录 JSON> \
    --out <工作目录>/project_params.json
```

从目录首行抽业主/项目名/招标编号；其余字段（机型 / 额定功率 / 风轮直径 / 轮毂高度 / 交货期 / 质保等）**不询问用户**，直接以 `[待填写：<字段说明>]` 字符串填入 `project_params.json`。已存在的 `project_params.json` 会保留已填值，只对仍为 `null/""` 的字段补占位符。

字段替换阶段（`preprocess.py`）把占位符字符串直接注入 docx；`verify.py` 扫描残留占位符并写入 `needs_review.md`。

### 第 3 步：构建装配计划

```bash
python3 scripts/build_assembly.py \
    --toc /tmp/toc.json \
    --wiki <wiki 路径> \
    --params <工作目录>/project_params.json \
    --out /tmp/assembly_plan.json
```

对每条 toc 条目：
- `normal` 标签 → 按 wiki `skeleton_section` 精确匹配素材
- `适配` 标签 → 精确匹配 + 标 `field_replace=True`
- `新增` 标签 → 无素材，标 NEEDS_REVIEW，生成 `[待填写：<title>]` 占位内容
- `前言` → 特殊匹配投标说明函（skeleton_section="前言"）

应用 `rules.md` 的通用↔定制：**叠加**（两份都纳入）、**覆盖**（只用定制）、**附加**（通用正文+定制附件）。

读卡片 `shift` / `attach_mode` / `heading_count` 写入 plan。

### 第 4 步：素材预处理

对 assembly_plan 里每份素材 docx，在 `/tmp/bid_prep/` 下生成 normalized 副本：

```bash
python3 scripts/cleaner.py <素材> <输出1>                                  # 删封面/空白页/重复标题/分页符
python3 scripts/preprocess.py <输出1> <输出2> --params <project_params>    # 样式归一 + 剥 numPr + 剥章节号前缀 + 标签清理 + [FIELD] 替换
```

`preprocess.py` 合并了早期的 `table_normalizer / shift_headings / field_replace`，并依赖 `numbering_fixer.py`、`fix_invalid_headings.py` 作为内部工具。项目参数里凡是 `[待填写：xx]` 占位符，会原样替换进 docx，交由 `verify.py` 在终检阶段记入 `needs_review.md`。

### 第 5 步：合并

```bash
python3 scripts/merger.py \
    --template templates/技术投标母版模板.docx \
    --plan /tmp/assembly_plan.json \
    --lib <素材库根目录> \
    --prep-dir /tmp/bid_prep/ \
    --out /tmp/bid_merged.docx
```

XML 级合并：relationship ID 去重、image 媒体合并、numbering.xml 兼容；[新增] 条目插占位；前言段作无编号 Heading 1；素材内部 Heading 只在匹配 S2 子目录时保留为导航 Heading，否则作为正文小标题保留，不进入 Word/OnlyOffice 导航。

### 第 6 步：终检打磨

```bash
python3 scripts/finalize.py \
    --in /tmp/bid_merged.docx \
    --params <工作目录>/project_params.json \
    --style references/heading_style.json \
    --out <工作目录>/投标文件-正文_<简称>_<时间戳>.docx
```

- 开篇插 Word TOC 域（Heading 1 "目录" + 域代码 `{ TOC \o "1-5" \h \z \u }` + `updateFields=true`）
- 页眉：项目名 + "投标文件-技术部分" + logo（高 0.96cm 宽 2.84cm 左对齐）
- 页码：TNR 小四居中，从正文首页起
- 兜底再刷 Heading 1-6 rFonts 和正文样式
- 确认多级列表样式为 `第X章 / X.Y / X.Y.Z / X.Y.Z.W / X.Y.Z.W.V`

### 第 7 步：验证与汇报（一把出终点）

```bash
python3 scripts/verify.py \
    --docx <输出> \
    --plan /tmp/assembly_plan.json \
    --params <工作目录>/project_params.json \
    --report <工作目录>/assembly_report.md \
    --review <工作目录>/needs_review.md
```

`needs_review.md` 汇总一切需人工确认项（**这是一把出后用户唯一要看的文件**）：
- project_params 未填字段（占位符 `[待填写：xx]` 清单）
- 残留占位符的章节定位
- [新增] 章节 — 素材缺失，用占位符段落顶上
- [未匹配] 章节 — wiki skeleton_section 未命中
- [适配] 章节 — 字段替换已做，需核对结果
- 第 0 步遗留的多候选冲突（如目录 docx 多份）

`assembly_report.md` 只做装配审计（Heading 统计 / 幽灵章节 / 非法 H1 / 相邻重复），不含待办。

## Backend Manifest 模式

在 `bid-project` 中，当前 `S4 生成标书` 后端会预先准备历史工作目录 `s7_assembly_workdir` 和 `s7_assembly_input.json`。这些名字为兼容旧脚本保留；收到这类任务时优先走 manifest：

```bash
python3 scripts/run_from_manifest.py \
  --manifest /data/documents/<projectId>/technical-workspace/s7_assembly_workdir/s7_assembly_input.json \
  --response summary
```

manifest 会指定：
- `tocJsonPath`：当前 `S1 模板与目录` 生成的目录 JSON 路径
- `wikiDir`：当前 `S1` 导出的数据库 Wiki 文件系统副本
- `materialLibraryDir`：后端按 Wiki 卡片 `material_id / path / cleaned_file_name` 从当前素材库导出的 Word 文件根目录
- `templateFile`：可选的投标正文模板，用于生成母版；没有时生成最小母版
- `projectParams` / `projectParamsPath`：项目参数预填与占位符写入
- `outputFile`：最终正文 docx 目标路径

`run_from_manifest.py` 只向 stdout 打印小型 JSON 摘要，完整报告留在 `assembly_report.md` 和 `needs_review.md`。

## 关键约束

- **Heading 样式名兼容**：`Heading 1-6` ↔ `标题 1-6` 双向映射（preprocess 处理）
- **编号方案**：Heading text 内嵌章节号（方案 B），不依赖 Word 多级列表
- **"前言"段**：无编号 Heading 1，用自定义样式 `PrefaceTitle` 或 `ilvl=-1`
- **（新增）/（适配）标签**：parse 阶段提取为 metadata，最终 docx 里剥除
- **表格格式**：宋体、五号或小四、居中、单倍行距、无缩进
- **图表题注**：**不重编号**，尊重素材原样
- **字体 rFonts 注入**：eastAsia=等线/等线Light、ascii=TNR（各级 Heading 不同），正文 eastAsia=等线
- **纸张方向**：保留素材原始 page orientation（不强制竖版），素材里为宽表设的 landscape section 合入后仍是横版
- **附字头自动重排**：`build_assembly.rearrange_appendices` 按 title 语义把错放的附字头挂到正确父 normal 下，原位置已正确时不动
- **整章素材 guard**：卡片 `skeleton_section` 深度 < entry `chapter_no_flat` 深度的差超过 1 时，fallback 匹配会跳过这张卡片，避免整章素材被误挂到子节（需在卡片上显式标 skeleton_section 为 "未明确" 让用户处理）
- **Section 隔离**：`merger._isolate_section` 为每份素材在 body 开头插入 continuous section break 带自身 sectPr，防止多份单 section 素材被 docxcompose 吞进同一 section 后被后续 landscape 素材污染
- **素材库纯 docx**：`投标资料库-通用/` 和 `投标资料库-定制/` 下**只允许 .docx**；`scripts/cleaner.py` 是独立的招标文件分析工具，不属于正式流程，其 CLI 已硬禁止向素材库写入 `*_cleaned.txt`
- **当前系统素材库适配**：Wiki 卡片里的 `material_id`、`cleaned_file_name`、`path` 是素材定位依据；后端在运行前将 MinIO/数据库素材导出成文件系统 docx，并把卡片 `path` 重写为导出后的相对路径。
- **空章节检测**：`verify.scan_docx` 体级遍历（段落 + 表格 + drawing/pict），对叶子 heading 后既无文字又无表格/图片的章节列入 `needs_review.md` 的"空章节告警"，这是暴露 wiki 归位错 / 素材空框架的关键守门哨
- **素材方向由素材决定**：skill 不自动纠正素材 page orientation；如果某素材（如宽表类）原本应横版却存成竖版，属**素材本身错误**，需要人工打开源 docx 改 page setup 再重跑

## 失败恢复

- `parse_toc` 抽不到章节号 → 检查目录 docx Heading 样式是否正确
- `init_params` 项目名抽偏 → 不中断，记入 `needs_review.md` 的"自动抽取结果可疑"段，由用户事后改 `project_params.json`
- `build_assembly` UNMATCHED 多 → 不中断，记入 `needs_review.md`，用户事后补 wiki 卡片再重跑
- `merger` 编号冲突 → numbering_fixer 兜底（旧 skill 的 SmartNumberingFixer）
- `finalize` TOC 域首次打开不展开 → 确认 `updateFields=true` 已注入

## 依赖

```bash
pip3 install --user python-docx lxml docxcompose PyYAML
```

## 工具使用要点

- `docxcompose` 做 section 级合并；大附件走 `merger.py` 的 zipfile XML 级合并
- 图片 relationship ID 冲突 → `merger.py` 内 ID 重映射
- 中文字体通过 lxml 改 `rPr/rFonts/@w:eastAsia` XML 注入（继承阶段 1 gen_toc.py 经验）
- officecli 只用于终检，不依赖其输出做决策

## 与 bid-toc-wiki-driven 的差异

| 维度 | bid-toc-wiki-driven | bid-tech-assembler |
|---|---|---|
| 产出 | 目录 JSON（空壳） | 正文 docx（完整内容） |
| 输入 | 招标 + 投标模板 + 附表 + wiki | S2 目录 JSON/docx + wiki + 素材库 |
| 核心决策 | skeleton_section 排布目录 | 目录 × 卡片 path → 素材合并顺序 |
| 编号 | 目录 Heading text 带章节号 | 多级列表自动编号，text 纯标题 |
| 附表 | 独立 A–I 区 | **本次不管** |
