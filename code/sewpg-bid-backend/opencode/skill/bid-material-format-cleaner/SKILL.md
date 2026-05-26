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

这是素材清洗通用工具：保留 driver 总控、Word 单临时副本事务与预检快路径，并补充两项能力：
- Word 标题在规范化阶段会去掉前置数字编号，并保留或补齐对应 Heading
- PDF 转 Word 时插入的标题默认带 `Heading 1`

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
4. 按后缀路由到 PDF / Excel / Word / `.doc` 分支
5. 维护 `OUTPUT_DIR` 的镜像目录结构
6. 汇总统计并输出统一报告


支持的输入类型：
- `.pdf`
- `.xlsx` / `.xls` / `.xlsm`
- `.docx`
- `.doc`

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
6. 在 `normalize` 阶段，若标题前存在数字编号，则删除编号，并保留或补齐对应 Heading 层级

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

### 3.4 `.doc` 分支

`.doc` 不再假定仓库里一定有额外转换脚本。

V4 规则：
- driver 先检查 LibreOffice / `soffice` 是否可用
- 可用：先转为临时 `.docx`，再走 Word 事务流程
- 不可用：直接记录为确定性 **FAIL**，而不是执行到中途才报错

## Step 4 — 输出状态定义

driver 会把每个文件固定归类为以下状态之一：

- `OK`：已完成转换 / 已切割并规范化
- `SKIP`：无需切割，仅规范化
- `REVIEW`：已完成事务内处理，但结果仍需人工复核
- `FAIL`：依赖缺失、文件损坏、`.doc` 转换器不可用等硬失败

## Step 5 — 报告通知

处理完成后，driver 在控制台输出统一报告，格式类似：

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
  [FAIL] subdir/file5.doc → - (未找到 LibreOffice/soffice，无法转换 .doc 文件)
═══════════════════════════════════════
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
