# 商务标 PDF MinerU 主线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将商务标 S1 PDF 解析主链路切换为 MinerU 驱动的文档解析引擎，并把 MinerU 产物适配为现有结构化解析和模板提取 skill 可复用的统一导航层。

**Architecture:** PDF 上传后先进入 `DocumentParseEngine`，首个 provider 固定为 `mineru`。MinerU 输出的 Markdown、JSON、表格、图片和页码信息统一转换为内部 `DocumentNav`，`bid-business-tender-structured-parser` 与 `bid-business-template-extractor` 只消费 `DocumentNav`，不直接依赖 MinerU 原始格式。质量不达标时按配置回退到轻量解析方案，DeepSeek-OCR 只作为低质量页兜底。

**Tech Stack:** Python 3、FastAPI、MinerU、PyMuPDF、python-docx、SQLite 导航库、现有 opencode skills、pytest/unittest、DeepSeek-OCR API。

---

## 决策和边界

- 当前主线是方案二：MinerU 作为商务标 PDF 首选解析引擎。
- 方案一轻量解析不删除，只作为 `BUSINESS_PDF_ENGINE_FALLBACK=lightweight` 的回退路径。
- MinerU 原始输出不进入业务 skill 契约；必须先适配为项目内部 `DocumentNav`。
- `pdf2docx` 不作为 MinerU 主线的一部分，只能在回退方案中作为可编辑 DOCX 候选。
- DeepSeek-OCR 不做全量 PDF OCR，只处理 MinerU 标记为扫描、低文本密度或解析失败的页面。

## MinerU 安装和部署边界

- MinerU 作为独立解析引擎部署，后端只通过 `DocumentParseEngine` 调用，不在业务 skill 内直接引入 MinerU SDK、CLI 参数或原始输出目录约定。
- 第一阶段优先支持本地 CLI 或内网服务两种部署形态，调用层只接收 PDF 路径、输出目录和解析模式，返回 Markdown、JSON、表格、图片、页码和质量报告路径。
- MinerU 的模型文件、运行依赖、GPU/CPU 资源、临时目录清理和并发限制由解析引擎层负责，S1 解析流程只感知 `documentNavPath`、`documentParseEngine` 和 `parseQualityPath`。
- 真实环境缺少 MinerU 或 MinerU 运行失败时，不阻塞 Word/DOCX 既有链路；PDF 可按配置回退到轻量解析，并在质量报告中记录 fallback 原因。

## 统一接口契约

新增内部中间结构，供 MinerU 主线和轻量回退共用：

- `DocumentNav`：单个解析任务的总入口，包含文档、页面、块、表格、图片、证据和质量报告。
- `DocumentPage`：页码、尺寸、文本密度、解析来源、页级截图和低质量标记。
- `DocumentBlock`：段落、标题、列表项、页眉页脚、表格占位或图片占位，必须带 `evidenceId`。
- `DocumentTable`：表格标题、页码范围、行列、单元格文本、跨页标记和 HTML/Markdown 备份。
- `DocumentImage`：页内图片、截图、扫描区域和来源 bbox。
- `DocumentEvidence`：`documentId/pageNo/blockId/tableId/bbox/sourceText/sourceEngine` 的可回查证据。
- `TemplateCandidate`：模板标题、候选类型、起止证据、置信度、原因和是否需要人工复核。
- `ParseQualityReport`：页级和文档级质量，用于触发 OCR 或 fallback。

建议配置项：

```env
BUSINESS_PDF_PARSE_ENGINE=mineru
BUSINESS_PDF_MINERU_ENABLED=true
BUSINESS_PDF_MINERU_MODE=auto
BUSINESS_PDF_ENGINE_FALLBACK=lightweight
BUSINESS_PDF_OCR_FALLBACK_ENABLED=true
```

---

### Task 1: 建立 DocumentNav 数据模型和质量报告契约

**Files:**
- Create: `code/sewpg-bid-backend/app/services/document_nav.py`
- Test: `code/sewpg-bid-backend/tests/test_business_pdf_document_nav.py`

- [ ] **Step 1: 写数据模型测试**

新增测试，验证最小 `DocumentNav` 能序列化、包含 evidence，并能表达表格和质量报告。

Run:

```powershell
cd D:\Project\codex\技术标\code\sewpg-bid-backend
pytest tests/test_business_pdf_document_nav.py -q
```

Expected: 初次运行失败，因为 `document_nav.py` 尚不存在。

- [ ] **Step 2: 实现最小数据模型**

在 `document_nav.py` 中使用 `dataclass` 或普通字典构造函数，提供：

```python
def build_document_nav(
    *,
    document_id: str,
    source_path: str,
    source_engine: str,
    pages: list[dict],
    blocks: list[dict],
    tables: list[dict],
    images: list[dict] | None = None,
    quality: dict | None = None,
) -> dict:
    ...
```

输出必须包含：

```json
{
  "schemaVersion": "business-document-nav-v1",
  "sourceEngine": "mineru",
  "documents": [],
  "pages": [],
  "blocks": [],
  "tables": [],
  "images": [],
  "evidence": [],
  "quality": {}
}
```

- [ ] **Step 3: 补齐 evidence 生成规则**

每个 block/table/image 都必须生成稳定 `evidenceId`，格式建议：

```text
DOC-1:P0001:B000001
DOC-1:P0001:T000001
DOC-1:P0001:I000001
```

- [ ] **Step 4: 运行测试**

Run:

```powershell
pytest tests/test_business_pdf_document_nav.py -q
```

Expected: PASS。

---

### Task 2: 新增 MinerU 解析引擎封装

**Files:**
- Create: `code/sewpg-bid-backend/app/services/document_parse_engine.py`
- Create: `code/sewpg-bid-backend/app/services/mineru_engine.py`
- Test: `code/sewpg-bid-backend/tests/test_business_pdf_mineru_engine.py`

- [ ] **Step 1: 写 provider 选择测试**

测试配置 `BUSINESS_PDF_PARSE_ENGINE=mineru` 时返回 MinerU provider；禁用 MinerU 时返回明确错误或 fallback 标记。

- [ ] **Step 2: 实现 `DocumentParseEngine` 抽象**

定义统一入口：

```python
class DocumentParseEngine:
    def parse_pdf(self, *, project_id: str, document: dict, output_dir: Path) -> dict:
        raise NotImplementedError
```

不要让业务代码直接调用 MinerU CLI 或 SDK。

- [ ] **Step 3: 实现 `MineruParseEngine` 外壳**

第一版只负责：

- 接收 PDF 路径。
- 创建 `document_parse/mineru/<documentId>/` 输出目录。
- 调用 MinerU CLI 或本地 SDK。
- 收集 MinerU 输出文件路径。
- 将调用失败写入 `ParseQualityReport`。

MinerU 的实际命令封装在一个函数中，便于测试 mock：

```python
def run_mineru_command(pdf_path: Path, output_dir: Path, mode: str) -> dict:
    ...
```

- [ ] **Step 4: 运行 provider 测试**

Run:

```powershell
pytest tests/test_business_pdf_mineru_engine.py -q
```

Expected: PASS。

---

### Task 3: MinerU 输出适配到 DocumentNav

**Files:**
- Create: `code/sewpg-bid-backend/app/services/mineru_nav_adapter.py`
- Test: `code/sewpg-bid-backend/tests/test_business_pdf_mineru_nav_adapter.py`

- [ ] **Step 1: 准备最小 MinerU fixture**

测试 fixture 使用本地小 JSON/Markdown 字符串模拟 MinerU 输出，必须包含：

- 标题：`第六章 投标文件格式`
- 模板标题：`一、投标函`
- 表格：`商务偏差表`
- 页码和 bbox。

- [ ] **Step 2: 实现 adapter**

新增：

```python
def convert_mineru_output_to_document_nav(
    *,
    document_id: str,
    source_path: Path,
    mineru_output_dir: Path,
) -> dict:
    ...
```

适配规则：

- Markdown 标题转 `DocumentBlock(type="heading")`。
- 普通段落转 `DocumentBlock(type="paragraph")`。
- 表格 HTML/Markdown 转 `DocumentTable`，同时在 blocks 中放表格占位块。
- 图片和页截图转 `DocumentImage`。
- 页码和 bbox 原样保留；缺失 bbox 时记录质量警告。

- [ ] **Step 3: 输出质量报告**

生成 `quality`：

```json
{
  "engine": "mineru",
  "status": "completed",
  "pageCount": 0,
  "lowQualityPages": [],
  "tableCount": 0,
  "warnings": []
}
```

- [ ] **Step 4: 运行 adapter 测试**

Run:

```powershell
pytest tests/test_business_pdf_mineru_nav_adapter.py -q
```

Expected: PASS。

---

### Task 4: 接入 S1 PDF 上传链路

**Files:**
- Modify: `code/sewpg-bid-backend/app/services/parsing.py`
- Test: `code/sewpg-bid-backend/tests/test_parse_pipeline.py`

- [ ] **Step 1: 写 S1 PDF MinerU 优先测试**

新增测试：上传 PDF 时，`parse_tender_documents` 优先调用 `DocumentParseEngine.parse_pdf()`，并把生成的 `documentNavPath` 写入 document metadata。

- [ ] **Step 2: 在 PDF 分支接入 MinerU**

在 `extension == ".pdf"` 分支中：

- 先保存原 PDF。
- 如果 `BUSINESS_PDF_MINERU_ENABLED=true`，调用 MinerU 引擎。
- 将 `documentNavPath`、`documentParseEngine`、`parseQualityPath` 写入 `metadata`。
- `texts_by_id[documentId]` 使用 `DocumentNav` 拼接出的可读文本，而不是只依赖 `pypdf`。

- [ ] **Step 3: 保留现有 PDF 文本兜底**

如果 MinerU 失败且 `BUSINESS_PDF_ENGINE_FALLBACK=lightweight`，保留现有 `extract_pdf_text()` 行为并记录 warning：

```text
MinerU 解析失败，已回退到轻量 PDF 文本解析。
```

- [ ] **Step 4: 运行 S1 PDF 接入测试**

Run:

```powershell
pytest tests/test_parse_pipeline.py::ParsePipelineTests::test_business_pdf_uses_mineru_document_nav_first -q
```

Expected: PASS。

---

### Task 5: 让结构化解析 skill 读取 DocumentNav

**Files:**
- Modify: `code/sewpg-bid-backend/opencode/skills/bid-business-tender-structured-parser/scripts/agentic/docx_indexer.py`
- Test: `code/sewpg-bid-backend/tests/test_business_agentic_parser.py`

- [ ] **Step 1: 写 DocumentNav 输入测试**

构造 manifest：

```json
{
  "documents": [
    {
      "id": "DOC-1",
      "sourcePath": "sample.pdf",
      "documentNavPath": "document_nav.json"
    }
  ]
}
```

期望 `s1parse prepare` 后 SQLite 中存在 blocks、tables、headings。

- [ ] **Step 2: 改造 `_read_document`**

读取优先级调整为：

1. `documentNavPath`
2. `.docx`
3. `textPath`
4. `.md/.txt`
5. `.pdf` 轻量文本兜底

`DocumentNav` 转 `IndexedDocument` 时：

- heading block 进入 `headings`。
- table 进入 `tables` 和 table rows/cells。
- block `evidenceId` 保留在 block id 或额外字段里。

- [ ] **Step 3: 运行结构化解析测试**

Run:

```powershell
pytest tests/test_business_agentic_parser.py::test_s1parse_prepare_reads_document_nav_for_pdf -q
```

Expected: PASS。

---

### Task 6: 让商务模板提取 skill 读取 DocumentNav

**Files:**
- Modify: `code/sewpg-bid-backend/opencode/skills/bid-business-template-extractor/scripts/agentic/doc_browser.py`
- Test: `code/sewpg-bid-backend/tests/test_business_template_extractor_skill_script.py`

- [ ] **Step 1: 写模板提取 DocumentNav 测试**

构造包含以下 block 的 `DocumentNav`：

- `第六章 投标文件格式`
- `一、投标函`
- `二、法定代表人授权委托书`
- `三、商务偏差表`

期望 `btplnav prepare` 后 `overview/search/window/read` 能返回这些 block。

- [ ] **Step 2: 改造 `doc_browser.prepare`**

读取优先级调整为：

1. `documentNavPath`
2. `.docx`

当输入为 `DocumentNav`：

- `blockId` 使用连续整数，兼容现有 `btplnav`。
- 保留 `sourceEvidenceId`、`pageNo`、`bbox`、`sourceEngine`。
- 表格 block 的 `rows` 来自 `DocumentTable`。

- [ ] **Step 3: 运行模板提取导航测试**

Run:

```powershell
pytest tests/test_business_template_extractor_skill_script.py::BusinessTemplateExtractorSkillScriptTests::test_btplnav_prepare_reads_document_nav_for_pdf -q
```

Expected: PASS。

---

### Task 7: 质量评估、OCR 兜底和 fallback

**Files:**
- Create: `code/sewpg-bid-backend/app/services/document_parse_quality.py`
- Modify: `code/sewpg-bid-backend/app/services/parsing.py`
- Test: `code/sewpg-bid-backend/tests/test_business_pdf_parse_quality.py`

- [ ] **Step 1: 写质量门禁测试**

覆盖：

- 低文本密度页触发 OCR。
- MinerU 无表格但页面存在表格关键词时触发人工复核 warning。
- MinerU 失败时触发 lightweight fallback。

- [ ] **Step 2: 实现质量评估**

新增：

```python
def evaluate_document_nav_quality(document_nav: dict) -> dict:
    ...
```

输出：

```json
{
  "status": "completed|fallback|needs_review|failed",
  "ocrPages": [],
  "fallbackUsed": false,
  "reviewRequired": false,
  "warnings": []
}
```

- [ ] **Step 3: 接入 DeepSeek-OCR 兜底**

只对页级 `ocrPages` 调用现有 OCR 服务；OCR 文本作为该页补充 block，不覆盖 MinerU 原始结果。

- [ ] **Step 4: 运行质量测试**

Run:

```powershell
pytest tests/test_business_pdf_parse_quality.py -q
```

Expected: PASS。

---

### Task 8: 真实样本评测和验收

**Files:**
- Create: `code/sewpg-bid-backend/eval/docs/business_pdf_mineru_eval.md`
- Test input: `C:\Users\99065\Downloads\商务标测试案例`

- [ ] **Step 1: 准备评测命令**

对 4 份真实 PDF 运行 MinerU 主线：

- 中电建
- 华能
- 国电投
- 大唐

记录：

- 页数
- block 数
- table 数
- 模板章节起始页
- 低质量页
- OCR 页数
- fallback 是否使用

- [ ] **Step 2: 验收模板章节定位**

必须定位到：

- 中电建第 85 页附近：`第五章 响应文件格式及内容`
- 华能第 89 页附近：`第六章投标文件格式`
- 国电投第 152 页附近：`第六章 投标文件格式`
- 大唐第 217 页附近：`第六章 应答文件格式`

允许页码偏差为 1 页，原因必须记录在评测文档中。

- [ ] **Step 3: 验收模板候选**

每份 PDF 至少识别出：

- 投标函/报价函/应答函
- 法定代表人或授权委托类模板
- 保证金或保函类模板
- 商务偏差表
- 资格审查或资格证明类模板

- [ ] **Step 4: 写评测结论**

在 `business_pdf_mineru_eval.md` 中给出：

- MinerU 是否继续作为主线。
- 是否需要启用 lightweight fallback。
- 哪些页面需要 DeepSeek-OCR。
- 哪些模板需要人工复核。

---

### Task 9: 文档、配置和回归测试收口

**Files:**
- Modify: `code/sewpg-bid-backend/README.md`
- Modify: `code/sewpg-bid-backend/app/core/config.py`
- Test: `code/sewpg-bid-backend/tests/test_parse_pipeline.py`
- Test: `code/sewpg-bid-backend/tests/test_business_template_extractor_skill_script.py`
- Test: `code/sewpg-bid-backend/tests/test_business_agentic_parser.py`

- [ ] **Step 1: 增加配置说明**

在 README 或后端配置说明中写清 MinerU 环境变量、输出目录和 fallback 行为。

- [ ] **Step 2: 增加 settings 字段**

在配置类中加入：

```python
business_pdf_parse_engine: str = "mineru"
business_pdf_mineru_enabled: bool = True
business_pdf_mineru_mode: str = "auto"
business_pdf_engine_fallback: str = "lightweight"
business_pdf_ocr_fallback_enabled: bool = True
```

- [ ] **Step 3: 跑关键回归**

Run:

```powershell
cd D:\Project\codex\技术标\code\sewpg-bid-backend
pytest tests/test_business_pdf_document_nav.py tests/test_business_pdf_mineru_engine.py tests/test_business_pdf_mineru_nav_adapter.py tests/test_business_pdf_parse_quality.py -q
pytest tests/test_business_agentic_parser.py -q
pytest tests/test_business_template_extractor_skill_script.py -q
pytest tests/test_parse_pipeline.py -q
```

Expected: PASS；如环境缺 MinerU，应跳过真实 MinerU 调用测试，只保留 adapter/mock 测试通过，并在评测文档记录。

## 验收标准

- PDF 主链路默认使用 MinerU。
- 结构化解析和模板提取均可从 `DocumentNav` 读取 PDF 内容。
- MinerU 输出不会直接泄露进业务 skill 契约。
- DeepSeek-OCR 只在低质量页或失败页兜底。
- MinerU 效果不佳时能切换到轻量 fallback。
- 真实样本 4 份 PDF 均能定位格式章节，并输出可回查 evidence。
