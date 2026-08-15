# parse_appendix

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/parse_appendix.py` |
| 层级 | 服务层 |
| 领域 | 解析与AI引擎 |
| 行数 | 2739 |

**职责**: 附表抽取与物化（parsing-01 自 `parsing.py` 拆出）：text/markdown/docx/document_nav 四路附表抽取、商务模板识别与语义复核、blankDocx 与承诺函 docx 物化落卷。

## 关键符号
- 抽取：`_extract_text_appendices`、`_extract_markdown_appendices`、`_extract_docx_appendices`、`_extract_document_nav_appendices`、`_extract_text_business_appendices`。
- 物化：`materialize_appendix_docx`、`materialize_business_commitment_letter_docx`、`materialize_parse_appendix_docx_assets`、`materialize_parse_business_commitment_letter_docx_assets`。

## 调用链
- **上游**: `parsing` 门面（re-export）；`bid_parse_service` 经 `materialize_parse_*_assets` 物化解析产物。
- **下游**: `parse_common`、`parse_profiles`、`agent_engine`（商务模板语义复核）、python-docx。

## 中间数据与状态
- 附表/承诺函 docx 落 parsed 卷与 workspace 目录；目录页伪影去重、附表重编号在 `_prepare_*_outputs`。
