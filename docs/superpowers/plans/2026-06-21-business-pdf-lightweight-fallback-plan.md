# 商务标 PDF 轻量解析后备 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 MinerU 主线效果不达标或运行不可用时，提供 PyMuPDF / pdfplumber / PyMuPDF Layout 驱动的商务标 PDF 轻量解析 fallback，并复用同一 `DocumentNav` 契约。

**Architecture:** fallback 不另起业务链路，而是用轻量开源解析模块生成与 MinerU 相同的 `DocumentNav`。S1 结构化解析和商务模板提取继续读取 `DocumentNav`，只通过配置切换解析 provider。`pdf2docx` 仅用于生成可编辑候选模板，不作为证据真源。

**Tech Stack:** Python 3、PyMuPDF、pdfplumber、PyMuPDF Layout、python-docx、现有 opencode skills、pytest/unittest、DeepSeek-OCR API。

---

## 启用条件和边界

- 当前优先方案二，方案一只作为后备：默认先验证 MinerU 主线，只有 MinerU 效果或部署可用性不达标时才切换到轻量解析。
- 仅当 MinerU 对真实样本的表格、阅读顺序、模板边界或部署性能不达标时启用。
- 与 MinerU 主线共用 `DocumentNav`，不新增第二套业务接口。
- `pdf2docx` 不作为主链路，不能替代 PDF 页码、bbox、截图和 evidence。
- DeepSeek-OCR 仍只处理低文本页、扫描页或 PyMuPDF/pdfplumber 无法可靠解析的页面。

建议配置项：

```env
BUSINESS_PDF_PARSE_ENGINE=lightweight
BUSINESS_PDF_LIGHTWEIGHT_FALLBACK_ENABLED=true
BUSINESS_PDF_PDF2DOCX_CANDIDATE_ENABLED=false
BUSINESS_PDF_NATIVE_TABLE_EXTRACTION_ENABLED=true
BUSINESS_PDF_OCR_FALLBACK_ENABLED=true
```

---

### Task 1: 建立 lightweight provider

**Files:**
- Create: `code/sewpg-bid-backend/app/services/lightweight_pdf_engine.py`
- Test: `code/sewpg-bid-backend/tests/test_business_pdf_lightweight_engine.py`

- [ ] **Step 1: 写 provider 测试**

构造一个 2 页 PDF fixture，要求 provider 输出：

- `sourceEngine == "lightweight"`
- 每页存在 `DocumentPage`
- 文本块进入 `DocumentBlock`
- 表格页进入 `DocumentTable`

- [ ] **Step 2: 实现 provider 外壳**

新增：

```python
class LightweightPdfParseEngine(DocumentParseEngine):
    def parse_pdf(self, *, project_id: str, document: dict, output_dir: Path) -> dict:
        ...
```

provider 内部调用 PyMuPDF 和 pdfplumber，不直接写业务字段。

- [ ] **Step 3: 运行测试**

Run:

```powershell
cd D:\Project\codex\技术标\code\sewpg-bid-backend
pytest tests/test_business_pdf_lightweight_engine.py -q
```

Expected: PASS。

---

### Task 2: PyMuPDF 文本块、标题和坐标抽取

**Files:**
- Modify: `code/sewpg-bid-backend/app/services/lightweight_pdf_engine.py`
- Test: `code/sewpg-bid-backend/tests/test_business_pdf_lightweight_engine.py`

- [ ] **Step 1: 写标题识别测试**

测试 PDF 包含：

- `第六章 投标文件格式`
- `一、投标函`
- `二、授权委托书`

期望输出 block 类型为 `heading`，并保留 `pageNo`、`bbox`、`fontSize`。

- [ ] **Step 2: 实现文本块抽取**

使用 PyMuPDF：

- `page.get_text("dict")` 提取 blocks、lines、spans。
- 短文本、字号较大、居中、编号开头的块标记为 heading。
- 页眉页脚标记为 `header_footer`，不参与模板边界优先判断。

- [ ] **Step 3: 运行标题测试**

Run:

```powershell
pytest tests/test_business_pdf_lightweight_engine.py::test_lightweight_extracts_headings_with_bbox -q
```

Expected: PASS。

---

### Task 3: pdfplumber/PyMuPDF 表格抽取

**Files:**
- Modify: `code/sewpg-bid-backend/app/services/lightweight_pdf_engine.py`
- Test: `code/sewpg-bid-backend/tests/test_business_pdf_lightweight_tables.py`

- [ ] **Step 1: 写表格抽取测试**

测试包含 `商务偏差表` 或 `条款号/条款名称/编列内容` 的表格，期望：

- `DocumentTable.rowCount > 0`
- `DocumentTable.colCount > 1`
- 表格 block 和 table 共用 evidence。

- [ ] **Step 2: 实现表格策略**

优先级：

1. PyMuPDF `page.find_tables()`。
2. pdfplumber `extract_tables()`。
3. 若两者都失败，保留表格疑似 block，并写入质量 warning。

- [ ] **Step 3: 运行表格测试**

Run:

```powershell
pytest tests/test_business_pdf_lightweight_tables.py -q
```

Expected: PASS。

---

### Task 4: 生成与 MinerU 共用的 DocumentNav

**Files:**
- Modify: `code/sewpg-bid-backend/app/services/lightweight_pdf_engine.py`
- Test: `code/sewpg-bid-backend/tests/test_business_pdf_document_nav.py`

- [ ] **Step 1: 写契约一致性测试**

同一个测试断言 MinerU adapter 和 lightweight provider 输出都包含：

- `schemaVersion`
- `pages`
- `blocks`
- `tables`
- `images`
- `evidence`
- `quality`

- [ ] **Step 2: 实现统一输出**

调用 `build_document_nav()`，不要在 lightweight provider 中手写另一套 schema。

- [ ] **Step 3: 运行契约测试**

Run:

```powershell
pytest tests/test_business_pdf_document_nav.py -q
```

Expected: PASS。

---

### Task 5: pdf2docx 可编辑候选模板

**Files:**
- Create: `code/sewpg-bid-backend/app/services/pdf2docx_candidate.py`
- Test: `code/sewpg-bid-backend/tests/test_business_pdf_pdf2docx_candidate.py`

- [ ] **Step 1: 写禁用默认测试**

当 `BUSINESS_PDF_PDF2DOCX_CANDIDATE_ENABLED=false` 时，不运行 pdf2docx。

- [ ] **Step 2: 实现候选生成器**

仅对已定位的模板页范围生成 DOCX 候选：

```python
def build_pdf2docx_candidate(*, pdf_path: Path, page_range: tuple[int, int], output_dir: Path) -> dict:
    ...
```

输出必须标记：

```json
{
  "candidateOnly": true,
  "sourceOfTruth": "document_nav",
  "quality": "unverified"
}
```

- [ ] **Step 3: 明确禁止作为 evidence 真源**

任何 `pdf2docx` 生成文件不得覆盖 `DocumentEvidence.sourcePath`。

- [ ] **Step 4: 运行测试**

Run:

```powershell
pytest tests/test_business_pdf_pdf2docx_candidate.py -q
```

Expected: PASS。

---

### Task 6: fallback 触发和回切策略

**Files:**
- Modify: `code/sewpg-bid-backend/app/services/document_parse_engine.py`
- Modify: `code/sewpg-bid-backend/app/services/parsing.py`
- Test: `code/sewpg-bid-backend/tests/test_business_pdf_engine_fallback.py`

- [ ] **Step 1: 写 fallback 测试**

模拟 MinerU 抛错，配置 `BUSINESS_PDF_ENGINE_FALLBACK=lightweight`，期望：

- 调用 lightweight provider。
- metadata 写入 `documentParseEngine == "lightweight"`。
- warning 包含 `MinerU 解析失败，已回退到轻量 PDF 解析。`

- [ ] **Step 2: 实现 fallback**

`DocumentParseEngine` factory 中增加：

```python
def parse_pdf_with_fallback(...):
    try:
        return mineru.parse_pdf(...)
    except Exception:
        return lightweight.parse_pdf(...)
```

仅当 fallback 配置开启时捕获；否则向上抛错。

- [ ] **Step 3: 运行 fallback 测试**

Run:

```powershell
pytest tests/test_business_pdf_engine_fallback.py -q
```

Expected: PASS。

---

### Task 7: DeepSeek-OCR 页级兜底

**Files:**
- Modify: `code/sewpg-bid-backend/app/services/lightweight_pdf_engine.py`
- Modify: `code/sewpg-bid-backend/app/services/document_parse_quality.py`
- Test: `code/sewpg-bid-backend/tests/test_business_pdf_parse_quality.py`

- [ ] **Step 1: 写 OCR 页级测试**

构造低文本密度页，期望质量报告中出现 `ocrPages`。

- [ ] **Step 2: 接入现有 OCR 服务**

只把低质量页渲染为图片后送 OCR，OCR 文本追加为 `DocumentBlock(sourceEngine="deepseek-ocr")`。

- [ ] **Step 3: 运行 OCR 质量测试**

Run:

```powershell
pytest tests/test_business_pdf_parse_quality.py -q
```

Expected: PASS。

---

### Task 8: 真实样本 fallback 评测

**Files:**
- Create: `code/sewpg-bid-backend/eval/docs/business_pdf_lightweight_fallback_eval.md`
- Test input: `C:\Users\99065\Downloads\商务标测试案例`

- [ ] **Step 1: 跑 4 份真实 PDF**

在 MinerU 不可用或被禁用时，使用 lightweight provider 跑：

- 中电建
- 华能
- 国电投
- 大唐

- [ ] **Step 2: 记录已知基线**

记录轻量方案实测基线：

- 中电建：141 页，PyMuPDF 表格约 57 个。
- 华能：135 页，PyMuPDF 表格约 47 个。
- 国电投：212 页，PyMuPDF 表格约 98 个。
- 大唐：364 页，PyMuPDF 表格约 194 个。

- [ ] **Step 3: 验收格式章节定位**

必须定位到：

- 中电建第 85 页附近。
- 华能第 89 页附近。
- 国电投第 152 页附近。
- 大唐第 217 页附近。

- [ ] **Step 4: 写 fallback 结论**

评估：

- 是否足以替代 MinerU。
- 哪些表格需要人工复核。
- 哪些页面需要 OCR。
- 是否建议开启 `pdf2docx` 候选。

## 验收标准

- lightweight provider 能独立生成 `DocumentNav`。
- 与 MinerU 主线共用同一 schema。
- MinerU 失败时可配置回退。
- `pdf2docx` 只作为候选，不作为真源。
- 真实样本能定位格式章节并提取核心模板候选。
