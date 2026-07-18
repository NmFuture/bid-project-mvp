# parsing

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/parsing.py` |
| 层级 | 服务层 |
| 领域 | 解析与AI引擎 |
| 行数 | 大型 |

**职责**: S1 解析核心引擎：直接复用技术标解析 Skill 的 `parser_core.parse_documents`（把 Skill scripts 目录插入 sys.path），按解析画像分类抽取（评分细则/项目基础信息等关键词类目），物化附表 blankDocx 与承诺函 docx，图片走 OCR。

## Input（输入）
- 招标文件（docx/pdf/图片，图片后缀走 `ocr_service`）；`parse_profiles` 的 BUSINESS/TECHNICAL 两套画像（Skill 名、类目差异）。

## Output（输出）
- 结构化解析结果（项目字段、章节树、附表清单等 contract）；`materialize_appendix_docx` / `materialize_business_commitment_letter_docx` 等物化产物；商务侧章节树落盘（`business_section_tree`）与模板抽取（`business_template_extractor`）。

## 调用链
- **上游**: `bid_parse_service`、`outline_generation`（OCR 兜底复用）。
- **下游**: Skill `parser_core`（bid-tech-tender-structured-parser 的脚本内核）、`ocr_service`、`opencode_client`（S1 语义增强，受 `S1_PARSE_OPENCODE_ENABLED` 开关）、`business_section_tree`、`business_template_extractor`、`parse_profiles`。

## 中间数据与状态
- parsed 数据卷内解析产物；类目关键词表 `PARSE_CATEGORIES`（scoring_criteria、project_basics 等）；文本预览截断 600 字。
