---
name: bid-material-format-cleaner
description: >
  清洗不同格式的素材文件（PDF/Excel/Word），统一转换为固定格式的 Word 文件，
  剥离封面、目录、前言等无用内容，只保留正文及其原有的标题、图片和排版。
  driver 总控基于原素材清洗流程，补充标题去编号并保留/补齐 Heading、以及 PDF 标题默认 Heading 1。
  当用户明确要求素材清洗、标题去编号清洗或 Heading 增强版清洗时使用此 skill。
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
  - Write
  - Edit
---

# bid-material-format-cleaner

批量清洗素材文件（PDF/Excel/Word），统一转换为标准 Word (.docx) 文件，剥离无用前序内容。

## 给调用方 Agent 的工作方式

这是一个「AI 编排 + 确定性脚本」的 skill：

- **你（Agent）负责编排判断**：确认素材目录、决定调用时机、读懂 driver 的报告与 `cleaning_manifest.json`，并据此决定后续动作（标 REVIEW 的要不要人工复核、FAIL 的为什么失败）。
- **`scripts/driver.py` 负责确定性转换**：所有 PDF/Excel/Word 的探针、切割、规范化、验证都在脚本里完成，保证输出稳定可复现。**不要**自己用 python-docx 手搓清洗逻辑去绕过 driver，那样会丢掉事务安全与镜像目录保证。

简言之：**判断交给你，确定性转换交给脚本。**

这是素材清洗通用工具：保留 driver 总控、Word 单临时副本事务与预检快路径，并补充两项能力：
- Word 中已是标题的段落（Heading 样式或 outline 层级）在规范化阶段去掉前置数字编号，并保留或补齐对应 Heading；不按"带编号、文字较短"把正文猜成标题——docx 里没有的层级不凭空捏造
- PDF 转 Word 时插入的标题默认带 `Heading 1`

## 处理范围

| 类型 | 是否清洗 | 说明 |
| --- | --- | --- |
| `.pdf` | ✅ 转 Word | 图片子文件夹 + Word 落到输出目录 |
| `.xlsx` / `.xls` / `.xlsm` | ✅ 转 Word | 每个 sheet 生成 Heading 2 + 表格 |
| `.docx` | ✅ 规范化 | 单临时副本事务 + 预检快路径 |
| 图片（png/jpg/jpeg/bmp/gif/webp/tif/tiff） | ❌ 不处理 | **图片证据不在本 skill 清洗范围**，由 wiki 侧（`bid-business-wiki-material-builder`）按原件直接挂载，不触发清洗稿引用 |
| `.doc` | ❌ 不支持 | 素材库统一以 `.docx` 收口，不再向 `.doc` 兼容 |

> 边界说明：driver 只扫描并处理上表中标记为 ✅ 的后缀，其余文件（含图片、`.doc`）会被直接跳过、不计入清洗统计。

## 配置

用户在调用时指定素材文件所在目录，或使用以下默认值：

```bash
SOURCE_DIR = （用户调用时指定，无默认值）
OUTPUT_DIR = Cleaned_Materials
```

## Step 0 — 环境准备

在本项目 Docker / worker 集成场景中，后端镜像已经预装依赖，并会设置
`FORMAT_CLEANER_ALLOW_SYSTEM_PY=1`，允许使用容器系统 Python 直接执行 driver。
本地人工运行时仍建议使用 venv。

### 0.1 优先使用当前目录已有 venv

若当前目录还没有 `venv/`，再执行：

```bash
python -m venv venv
```

### 0.2 只使用 venv 解释器，不依赖 activate

**Windows：**

```bash
VENV_PY="./venv/Scripts/python"
```

**macOS / Linux：**

```bash
VENV_PY="./venv/bin/python"
```

**执行纪律：**
- 不要再执行 `./venv/Scripts/activate`
- 不要裸跑 `python xxx.py`
- 不要裸跑 `pip install ...`
- 统一使用 `"$VENV_PY" -m ...` 或 `"$VENV_PY" <script>`

### 0.3 依赖安装

可显式安装，也可交给 driver 自动补齐缺失依赖；两种方式都必须走当前 venv。

```bash
"$VENV_PY" -m pip install pymupdf python-docx pandas openpyxl lxml
```

### 0.4 officecli / Git Bash 说明

- V4 仍然**优先**使用 `officecli` 做 Word 探针与验证
- 若 `officecli` 缺失、报错或在 Windows/Git Bash 下触发路径问题，driver 会**立即回退**到 `word_cleaner.py`
- driver 内部会为子进程设置 `MSYS2_ARG_CONV_EXCL="*"`，因此**不需要**再手工 `export`

## Step 1 — 唯一执行入口：driver

V4 不再要求模型手工逐段敲多套 shell 命令。统一调用：

```bash
"$VENV_PY" "<skill-path>/scripts/driver.py" "<SOURCE_DIR>" --output-dir "<OUTPUT_DIR>"
```

例如：

```bash
"$VENV_PY" "<skill-path>/scripts/driver.py" "D:/Project/Cluade_Code/qingxi/投标资料库-项目定制模板-2020414" --output-dir "D:/Project/Cluade_Code/qingxi/Cleaned_Materials"
```

## Step 2 — driver 内部职责

driver 负责完成以下全部编排动作：

1. 校验当前解释器确实来自 venv
2. 在当前 venv 中检测并补齐运行依赖
3. 递归扫描 `SOURCE_DIR` 下所有素材文件
4. 按后缀路由到 PDF / Excel / Word 分支
5. 维护 `OUTPUT_DIR` 的镜像目录结构
6. 汇总统计并输出统一报告
7. 写入结构化清洗清单 `cleaning_manifest.json`，供后端保存清洗状态、来源路径和复核信息


支持的输入类型：
- `.pdf`
- `.xlsx` / `.xls` / `.xlsm`
- `.docx`

## Step 3 — 各分支处理规则

### 3.1 PDF 分支

复用 skill 内置 `scripts/pdf_to_word.py`，并且**必须**通过 `--out-dir` 语义输出到目标目录：

- 图片子文件夹写入 `OUTPUT_DIR/<relative_subdir>/<pdf_stem>/`
- Word 文件写入 `OUTPUT_DIR/<relative_subdir>/<pdf_stem>.docx`
- 原始 PDF 所在目录不留下任何图片或中间 docx
- 插入的 PDF 标题默认带 `Heading 1`，同时保持现有首页标题与图片同段落的排版策略

### 3.2 Excel 分支

复用 skill 内置 `scripts/excel_to_word.py`：

- 每个 sheet 生成 Heading 2 + 标准表格
- 输出固定落到 `OUTPUT_DIR/<relative_subdir>/<stem>.docx`
- 保留原始行列结构

### 3.3 Word 分支

Word 文件采用 **“单临时副本事务 + 预检快路径”**：

1. 从源文件复制到单个 ASCII 临时工作目录
2. 在这份临时副本上完成全部探针、trim、normalize、验证
3. 成功 / 复核结果一次性拷回 `OUTPUT_DIR`
4. 原始文件始终不修改
5. 输出文件不再先落地再被反复改写
6. 在 `normalize` 阶段，若真实标题（Heading 样式或 outline 层级）前存在数字编号，则删除编号，并保留或补齐对应 Heading 层级；无标题证据的正文保持原样，不猜层级

#### 预检快路径

先做一次廉价判断：
- 优先 `officecli view outline/text`
- 失败时立即回退 `word_cleaner.py peek`
- 只读取足够判断正文起点的前部信息

若前部已明显是正文：
- 直接判定为 **SKIP**
- 跳过 trim
- 只做 `normalize + verify`

若前部存在明显封面 / 目录 / 前言 / 声明 / 审批 / 修订记录：
- 进入一次锚点定位
- 执行一次 trim
- 然后 `normalize + verify`

若文档空白、仅前序材料、或无法稳定识别正文起点：
- 直接落到 **REVIEW** 或明确失败
- 不进入无上限试错

#### V4 Word 流程纪律

默认只允许：
1. 探针
2. 预检判断
3. 最多一次 trim
4. normalize
5. 验证
6. 如验证失败，最多一次纠偏（重新定位 + trim + normalize + 再验证）

到此为止，禁止进入旧版那种反复“看一眼再删一段”的循环微操。

## Step 4 — 输出状态定义

driver 会把每个文件固定归类为以下状态之一：

- `OK`：已完成转换 / 已切割并规范化
- `SKIP`：无需切割，仅规范化
- `REVIEW`：已完成事务内处理，但结果仍需人工复核
- `FAIL`：依赖缺失、文件损坏等硬失败

## Step 5 — 报告通知

处理完成后，driver 在控制台输出统一报告，并默认在输出目录写入
`cleaning_manifest.json`。后端集成会读取这份 JSON，把 `status/detail`、源文件相对路径、清洗稿相对路径、是否可检索、是否需人工复核等信息保存到素材元数据，供商务 Wiki 和后续素材匹配引用。

如需指定 JSON 清单位置：

```bash
"$VENV_PY" "<skill-path>/scripts/driver.py" "<SOURCE_DIR>" --output-dir "<OUTPUT_DIR>" --report-file cleaning_manifest.json
```

JSON 结构固定包含：

```json
{
  "schemaVersion": "material-cleaning-manifest/v1",
  "generatedAt": "2026-05-28T00:00:00Z",
  "sourceDir": "<SOURCE_DIR>",
  "outputDir": "<OUTPUT_DIR>",
  "summary": {
    "total": 1,
    "successTotal": 1,
    "reviewTotal": 0,
    "failedTotal": 0,
    "byStatus": {"OK": 1},
    "byKind": {"excel": {"OK": 1}}
  },
  "records": [
    {
      "kind": "excel",
      "status": "OK",
      "detail": "已转换为 Word",
      "relativeSourcePath": "subdir/file.xlsx",
      "relativeOutputPath": "subdir/file.docx",
      "sourceFileName": "file.xlsx",
      "outputFileName": "file.docx",
      "outputExists": true,
      "isUsableForRetrieval": true,
      "needsHumanReview": false
    }
  ]
}
```

控制台报告格式类似：

```text
═══════════════════════════════════════
        素材清洗报告（V4）
═══════════════════════════════════════
源目录: <SOURCE_DIR>
输出目录: <OUTPUT_DIR>
───────────────────────────────────────
文件统计:
  PDF  文件: X 个（成功 X / 失败 X）
  Excel文件: X 个（成功 X / 失败 X）
  Word 文件: X 个（清洗 X / 无需切割 X / 人工复核 X / 失败 X）
  总计: X 个文件（成功 X / 异常 X）
───────────────────────────────────────
详细清单:
  [OK] subdir/file1.pdf → subdir/file1.docx (已转换为 Word)
  [SKIP] subdir/file2.docx → subdir/file2.docx (无需切割；已规范化)
  [OK] subdir/file3.docx → subdir/file3.docx (锚点: 1 项目概况；已规范化)
  [REVIEW] subdir/file4.docx → subdir/file4.docx (已规范化；需人工复核)
  [FAIL] subdir/file5.xlsx → - (文件损坏，无法解析)
═══════════════════════════════════════
```

### 飞书通知（可选）

driver 可在处理完成后向飞书群推送一条文字汇总，默认开启，可用 `--no-feishu` 关闭（后端集成调用时固定带 `--no-feishu`）。

webhook 地址通过环境变量 `FORMAT_CLEANER_FEISHU_WEBHOOK` 提供，**不再硬编码在脚本中**。未配置该变量时直接跳过通知，不影响清洗主流程。

```bash
export FORMAT_CLEANER_FEISHU_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/xxxx"
```



## 注意事项

- **V3 保持不动**：V4 是独立副本，不修改原有 `format-cleaner-v3`
- **安全第一**：所有操作只在副本或临时事务副本上进行，原始文件绝不修改
- **零污染**：所有产物只写入 `OUTPUT_DIR` 或系统临时目录，源目录中不留下中间文件
- **目录镜像**：输出目录完整保留原始素材的子目录层级结构
- **工具回退纪律**：`officecli` 是首选；一旦失败，立即回退 `word_cleaner.py`，不要反复重试失败命令
- **单次纠偏上限**：验证失败时最多补做 1 次“重新定位锚点 + trim + normalize”；若仍异常，标记人工复核
- **幂等性**：若 `OUTPUT_DIR` 已存在同名文件，直接覆盖
- **错误容忍**：单个文件失败不影响其他文件处理，失败信息进入最终报告
