---
name: bid-tech-assembler
description: 当需要在 S4 生成标书阶段组装技术标正文 docx 时使用。输入已确认目录 JSON + Wiki + 素材库导出 Word + 项目参数，输出正文 docx 与结构化检查结果。只管正文，不管附表 A–I。
allowed-tools: [Read, Glob, Grep, Bash, Write, Edit]
---

# 投标文件正文组装 — wiki 驱动 + 母版起稿（方案 B：文本前缀编号）

你是投标文件正文组装专家，服务于**上海电气风电集团**（投标方固定）。

**一把出策略**：不中途询问用户；所有缺失项写占位符 `[待填写：xx]`，需人工确认项进入结构化 `warnings`。阶段命名与历史别名（`s7_assembly_workdir` 等）见 `../STAGES.md`。

## 方案 B 核心原则

> 编号方案以代码为准：`merger.py`（手插 `"{chapter_no}  {title}"` Heading）+ `finalize.py`（剥残留 numPr）+ `tools/clean_master_numbering.py`（母版样式解绑）。改动编号策略必须同步更新本节。

- **Heading text 直接带章节号字符串**（"第一章  标前概述" / "1.1  xxx" / "5.8.1  xxx"），不依赖 Word 多级列表自动编号
- **母版 Heading 1-6 样式已解绑 numId**（由 tools/clean_master_numbering.py 保证）
- 素材 docx 预处理时剥 `w:numPr`；最终 Word 导航 Heading **只来自 S2 目录**。素材内部 Heading 若能匹配当前父章节下的 S2 子目录，则改写为该 S2 编号 Heading；其余素材内部 Heading 降级为正文小标题并清除段落级 `w:outlineLvl`
- 素材首 Heading 若文本匹配 toc 标题，**物理去重**（避免相邻重复）；不在 S2 目录内的素材内部 Heading 不进入左侧导航/TOC
- 前言段 text="前言  投标说明函"，Heading 1 样式但无章节号前缀
- **封面**作为 skeleton_section="封面" 的 L0 条目，attach_mode=cover，置于文档最前

流水线：`parse_toc`（优先读 S2 JSON）+ `init_params` → `build_assembly`（plan 首位插 COVER） → `merger`（docxcompose + 素材 Heading 对齐 S2/降级）→ `finalize`（TOC 域插于封面后、首 Heading 前）→ `verify`（硬性检查：幽灵章节=0 / 非法 H1=0 / 相邻重复=0）。

## 上游关系

目录 JSON 由 `bid-tech-outline-generator`（S1 模板与目录）产出。本 skill 只认最终审核确认的目录结果，优先读取 `bid-toc-json-v1` JSON；仍兼容历史目录 docx。

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

**非交互策略**：多份匹配自动选 mtime 最新那份，其它候选记入 warning；缺失 wiki 等必需输入才中止。单份素材不存在、损坏或合并失败时记录 warning 并继续，目录节点没有任何可用素材时保留 Heading 并插入简短占位提示。

## 输出约定

- **位置**：工作目录下
- **文件名**：`投标文件-正文_<项目简称>_<YYYYMMDDHHMM>.docx`
- **附带**：`assembly_plan.json`（章节级装配结果）以及内部 `assembly_merge_result.json`、`assembly_verify_result.json`
- **返回契约**：始终包含 `outputFile`、`planFile`、`summary`、`warnings`；`summary.warningCount` 为各 warning 的 `count` 总和，`warnings[]` 每项只含 `code`、`message`、`count`

## 执行流程

### 第 0 步：环境与文件校验（无交互）

1. `python3 -c "import docx, lxml, docxcompose"` 失败 → 提示 `pip install python-docx lxml docxcompose`，中止
2. 后端 manifest 优先传入 S2 的目录 JSON；无 manifest 时 Glob 工作目录定位目录 JSON/docx，多份 → **自动选 mtime 最新**，其它候选进入结构化 warning
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

字段替换阶段（`preprocess.py`）把占位符字符串直接注入 docx；`verify.py` 扫描残留占位符并把统计写入验证 JSON，由 runner 汇总为 warning。

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

`preprocess.py` 合并了早期的 `table_normalizer / shift_headings / field_replace`，并依赖 `numbering_fixer.py`、`fix_invalid_headings.py` 作为内部工具。项目参数里凡是 `[待填写：xx]` 占位符，会原样替换进 docx，交由 `verify.py` 在终检阶段扫描并汇总。

### 第 5 步：合并

```bash
python3 scripts/merger.py \
    --template templates/技术投标母版模板.docx \
    --plan /tmp/assembly_plan.json \
    --lib <素材库根目录> \
    --prep-dir /tmp/bid_prep/ \
    --out /tmp/bid_merged.docx
```

XML 级合并：relationship ID 去重、image 媒体合并、numbering.xml 兼容；[新增] 条目插占位；前言段作无编号 Heading 1；素材内部 Heading 只在匹配 S2 子目录时保留为导航 Heading，否则作为正文小标题保留，不进入 Word/OnlyOffice 导航。单份素材失败不阻断后续素材；一个目录节点的所有素材均失败时，保留该节点 Heading 并插入 `[缺失：...——没有可用素材，请补充后重试]`。

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
- 兜底剥除样式与正文残留 numPr（方案 B 不用多级列表），确认各级 Heading text 的章节号前缀形态为 `第X章 / X.Y / X.Y.Z / X.Y.Z.W / X.Y.Z.W.V`

### 第 7 步：验证与汇报（一把出终点）

```bash
python3 scripts/verify.py \
    --docx <输出> \
    --plan /tmp/assembly_plan.json \
    --params <工作目录>/project_params.json \
    --result <工作目录>/assembly_verify_result.json
```

`verify.py` 保留 Heading 统计、幽灵章节、非法 H1、相邻重复、空章节和残留占位符扫描，只返回紧凑 JSON。runner 将素材失败、未匹配目录和验证风险统一汇总到 `summary.verification` 与 `warnings`，每条 warning 只含 `code`、`message`、`count`。

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

`run_from_manifest.py` 只向 stdout 打印小型 JSON 摘要。摘要中的 `warnings` 至少覆盖素材缺失、素材合并失败、目录未匹配、残留占位符和格式风险；`assembly_plan.json` 继续保留已组装、未匹配、需复核和结构节点状态。兼容字段 `assemblyReport`、`needsReview` 保留但固定为空字符串。

## 关键约束（策略级）

- **编号方案**：Heading text 内嵌章节号（方案 B），不依赖 Word 多级列表
- **"前言"段**：无编号 Heading 1
- **（新增）/（适配）标签**：parse 阶段提取为 metadata，最终 docx 里剥除
- **图表题注不重编号**、**纸张方向由素材决定**（skill 不自动纠正）
- **素材库纯 docx**：`投标资料库-通用/` 和 `投标资料库-定制/` 下只允许 `.docx`
- **`references/heading_style.json` 是共享契约**：format-cleaner 和后端两处 service 直接消费，移动/改名前必须同步全部消费方

实现级细节（样式映射、rFonts 注入、Section 隔离、整章素材 guard、附字头重排、空章节检测等）见 `references/constraints.md`，修改对应脚本时同步更新。

## 失败恢复

- `parse_toc` 抽不到章节号 → 检查目录 docx Heading 样式是否正确
- `init_params` 项目名抽偏 → 不中断，记入结构化 warning，由用户事后改 `project_params.json`
- `build_assembly` UNMATCHED 多 → 不中断，记入结构化 warning，用户事后补 wiki 卡片再重跑
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
