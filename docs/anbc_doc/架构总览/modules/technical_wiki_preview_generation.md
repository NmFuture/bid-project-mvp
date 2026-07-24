# technical_wiki_preview_generation

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_wiki_preview_generation.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 495 |

**职责**: 技术素材文件级 AI 预览的增量生成器：按内容指纹（headings/paragraphs/tableCount 的 sha256）判断是否需重新生成，批量构建 prompt 调 LLM，产出「导读/要点/关键参数/召回提示」，缓存到素材 `ext_fields.techWikiPreview`。

## Input / Output
- Input: 三级目录 JSON 索引文件清单、docx 剖析（`extract_docx_profile`，同步上限 `MAX_SYNC_DOCX_BYTES`）。
- Output: 预览对象（schema 由 Skill 侧 `PREVIEW_SCHEMA_VERSION` 定），并发 4、批量 `PREVIEW_BATCH_SIZE`；LLM 失败回退本地要点提取（上限 5 条）。

## 调用链
- **上游**: `technical_wiki_generation`（enrich 入口，后台 preview_mode=generate 路径）。
- **下游**: `technical_wiki_preview_prompt`（Skill 桥接的 prompt/解析/证据片段）、`wiki_blueprint_common`、opencode（经上游注入的客户端）。

## 中间数据与状态
- `ext_fields.techWikiPreview`（DB 缓存，含指纹）；tier 标签映射（standard 标准文件/customer 客户定制/project 项目定制）。
