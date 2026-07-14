# technical_wiki_generation

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_wiki_generation.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 140 |

**职责**: 技术标 Wiki 生成——纯「脚本+Skill」确定性链路（与商务标 LLM 精修链路完全解耦）：Wiki 树严格镜像素材三级目录 JSON 索引，无 LLM 语义精修。

## 流程
读三级目录 JSON 索引 → 写 manifest（`parsed卷/_wiki_build/` 临时目录，root 标题「技术标Wiki（自动生成）」）→ subprocess 跑 Skill `bid-tech-wiki-material-builder` → blueprint 导入技术素材库；随后 `enrich_technical_wiki_previews` 增量补 AI 预览。

## Input / Output
- Input: `generate_technical_wiki(reference_path, mode, fallback_to_deterministic)`（bootstrap 端点）。
- Output: Wiki 节点树（确定性镜像）+ 文件级 AI 预览注入。

## 调用链
- **上游**: `routes/technical.py` `wiki/bootstrap`。
- **下游**: `technical_material_index`（索引读取）、Skill `bid-tech-wiki-material-builder`、`technical_wiki_preview_generation`、`technical_material_store`（导入）、`wiki_blueprint_common`、`ocr_service`。

## 中间数据与状态
- `_wiki_build` 共享构建目录；Wiki 节点表；「刷新/重建 Wiki」共用此链路（preview_mode=cached 秒级）。
