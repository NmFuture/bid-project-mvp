# wiki_blueprint_common

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/wiki_blueprint_common.py` |
| 层级 | 服务层 |
| 领域 | Wiki通用 |
| 行数 | 250 |

**职责**: 两轨 Wiki 生成共用的最小纯工具集（刻意不含任何 bid_type 分流与业务逻辑）：LLM 回复 JSON 容错解析（剥 ```围栏/截取花括号）、blueprint 归一化、本地 Skill 脚本执行 `run_local_wiki_skill`、docx 剖析 `extract_docx_profile`（标题树/段落/表数，同步上限 `MAX_SYNC_DOCX_BYTES`）。

## 调用链
- **上游**: `business_wiki_generation`、`technical_wiki_generation`、`technical_wiki_preview_generation`、`audit_service`、`bid_fill_generation_state`。
- **下游**: subprocess（Skill 脚本）、zipfile/ET（OOXML 直读）。

## 中间数据与状态
- 常量：`MAX_CARD_EXCERPT_PARAGRAPHS`、`MAX_SYNC_DOCX_BYTES`。
