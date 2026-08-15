# parse_extract

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/parse_extract.py` |
| 层级 | 服务层 |
| 领域 | 解析与AI引擎 |
| 行数 | 420 |

**职责**: S1 文本提取层（parsing-01 自 `parsing.py` 拆出）：docx/pdf 文本抽取、图片与商务 PDF 页 OCR 兜底、document_nav 质量合并与 finalize、docling/文档引擎 PDF 解析入口。

## 关键符号
- `extract_docx_text`、`extract_pdf_text`、`_ocr_fallback_text`、`_ocr_business_pdf_pages`、`_parse_pdf_with_document_engine`、`_finalize_loaded_document_nav`、`_merge_document_nav_quality`。

## 调用链
- **上游**: `parsing` 门面（re-export）。
- **下游**: `ocr_service`、`docling_engine`、`document_nav`、`document_parse_quality`、`parse_common`。

## 中间数据与状态
- document_nav 与质量评估产物落 parsed 卷；OCR 结果追加进 document_nav 块。
