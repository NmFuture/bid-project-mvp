# technical_wiki_preview_prompt

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_wiki_preview_prompt.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 36 |

**职责**: importlib 桥接 Skill `bid-tech-wiki-material-builder/scripts/technical_wiki_preview.py`：暴露预览 prompt 构建/回复解析/证据片段构建函数与 schema 常量——后端与 Skill 共用同一份预览逻辑。

## Input / Output
- 透传：`build_(batch_)preview_prompt`、`parse_(batch_)preview_reply`、`build_evidence_segments`、`PREVIEW_SCHEMA_VERSION`、`PREVIEW_BATCH_SIZE`；脚本缺失启动即 RuntimeError。

## 调用链
- **上游**: `technical_wiki_preview_generation`。
- **下游**: Skill 脚本（注册为 `technical_wiki_preview_skill`）。

## 中间数据与状态
- 无。
