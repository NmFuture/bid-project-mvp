# parsing

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/parsing.py` |
| 层级 | 服务层 |
| 领域 | 解析与AI引擎 |
| 行数 | 892 |

**职责**: S1 解析门面（parsing-01 拆分后）：主入口 `parse_tender_documents` 编排全链路——解析画像 → 文本提取 → Skill 语义解析（技术标分片并发/单会话兜底）→ 契约总装 → 附表与承诺函物化；实现已拆至 `parse_common`/`parse_extract`/`parse_business_fields`/`parse_appendix`/`parse_s1_skill`，本模块 re-export 全部旧符号，保持 `app.services.parsing.<符号>` 可解析、可 patch。

## Input（输入）
- 招标文件（docx/pdf/图片，图片后缀走 `ocr_service`）；`parse_profiles` 的 BUSINESS/TECHNICAL 两套画像（Skill 名、类目差异）。

## Output（输出）
- 结构化解析结果（项目字段、章节树、附表清单等 contract）；附表 blankDocx 与承诺函 docx 物化产物（实现于 `parse_appendix`）；商务侧章节树落盘（`business_section_tree`）与模板抽取（`business_template_extractor`）。

## 调用链
- **上游**: `bid_parse_service`、`outline_generation`（OCR 兜底复用）。
- **下游**: 同服务包 `parse_common`/`parse_extract`/`parse_business_fields`/`parse_appendix`/`parse_s1_skill`；Skill `parser_core`（bid-tech-tender-structured-parser 的脚本内核）、`ocr_service`、`agent_engine`（S1 语义增强，`AgentEngineFactory` 创建引擎）、`business_section_tree`、`business_template_extractor`、`parse_profiles`。

## 中间数据与状态
- parsed 数据卷内解析产物；门面自有逻辑仅剩 `_extract_structured_requirements` 与商务本地契约合并（`_business_local_contract_result`/`_merge_business_local_artifacts`）。
